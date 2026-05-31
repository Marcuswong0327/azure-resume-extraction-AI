import os

import streamlit as st
import pandas as pd
import json
import traceback
from pdf_processor import PDFProcessor
from word_processor import WordProcessor
from text_processor import TextProcessor
from ai_parser import AIParser
from excel_exporter import ExcelExporter
from blob_uploader import BlobUploader
import base64

# Hard cap: one batch cannot exceed this many files (uploader + processing).
MAX_FILES_PER_BATCH = 300

# Tabs: each country runs the same pipeline with its own state namespace and
# phone-number standardization target (+61 for AU, +60 for MY).
COUNTRIES = ["AU", "MY"]


def _key(name, country):
    """Build a country-namespaced session-state key."""
    return f"{name}_{country}"


@st.cache_resource(show_spinner=False)
def get_blob_uploader():
    """Return a configured BlobUploader, or None when archiving is disabled.

    Cached as a process-wide singleton: Streamlit reruns the whole script on
    every interaction, so building the client (and its one-time CreateContainer
    probe) per call would spam the storage account with transactions. Caching
    builds it once. Returns None for graceful degradation when Azure is off.
    """
    try:
        return BlobUploader.from_secrets(st.secrets)
    except Exception:
        return None


def main():
    st.set_page_config(
        page_title="Resume Parser 2.0",
        page_icon="📄",
        layout="wide"
    )
    
    st.title("📄 Resume Parser 2.0")
    st.title("💰Road to Million Biller!!!")

    # Initialize per-country session state
    for country in COUNTRIES:
        if _key('processed_candidates', country) not in st.session_state:
            st.session_state[_key('processed_candidates', country)] = []
        if _key('processing_complete', country) not in st.session_state:
            st.session_state[_key('processing_complete', country)] = False
        if _key('processing_in_progress', country) not in st.session_state:
            st.session_state[_key('processing_in_progress', country)] = False

    # Shared branding logo, shown once above the tabs
    _logo = "linktal logo transparent copy.png"
    if os.path.isfile(_logo):
        st.image(_logo, width=350)

    # Check credentials availability
    credentials_status = check_credentials()

    tabs = st.tabs(COUNTRIES)
    for tab, country in zip(tabs, COUNTRIES):
        with tab:
            render_country_tab(country, credentials_status)


def render_country_tab(country, credentials_status):
    col1, col2 = st.columns([2, 1])

    with col1:
        uploaded_files = st.file_uploader(
            f"Upload resumes (max {MAX_FILES_PER_BATCH} files per batch)",
            type=['pdf', 'docx', 'doc', 'txt'],
            accept_multiple_files=True,
            key=_key('uploader', country),
        )

        if get_blob_uploader() is None:
            st.caption(
                "Resume archiving is disabled — add Azure secrets to store files "
                "and enable durable download links."
            )

        over_limit = bool(uploaded_files) and len(uploaded_files) > MAX_FILES_PER_BATCH

        if uploaded_files and over_limit:
            st.error(
                f"Hard limit exceeded: at most **{MAX_FILES_PER_BATCH}** files per batch. "
                f"You selected **{len(uploaded_files)}**. Remove files until you are at or below the limit, then upload again."
            )

        if uploaded_files and not over_limit:
            st.success(f"✅ {len(uploaded_files)} file(s) uploaded successfully")

            # Display uploaded files
            with st.expander("📋 Uploaded Files", expanded=True):
                for i, file in enumerate(uploaded_files, 1):
                    file_type = file.name.split('.')[-1].upper()
                    st.write(f"{i}. {file.name} ({file.size} bytes) - {file_type}")

            # Process files button
            process_disabled = (
                not credentials_status['claude_status']
                or st.session_state[_key('processing_in_progress', country)]
            )

            if st.button(
                "Process Resumes",
                type="primary",
                use_container_width=True,
                disabled=process_disabled,
                key=_key('process_btn', country),
            ):
                if not credentials_status['claude_status']:
                    st.error("Please configure OpenRouter API credentials before processing.")
                else:
                    process_resumes(uploaded_files, country)

    with col2:
        st.header("Processing Status")

        if st.session_state[_key('processing_in_progress', country)]:
            st.info("Processing")
        elif st.session_state[_key('processed_candidates', country)]:
            st.metric("Processed Candidates", len(st.session_state[_key('processed_candidates', country)]))

            if st.session_state[_key('processing_complete', country)]:
                st.success("Processed successfully!")

                if st.button(
                    "Download Excel Report",
                    type="secondary",
                    use_container_width=True,
                    key=_key('download_btn', country),
                ):
                    generate_and_download_excel(country)
            else:
                st.info("No candidates processed yet.")

    # Display processed candidates
    candidates = st.session_state[_key('processed_candidates', country)]
    if candidates:
        st.header("Processed Candidates")

        # Create DataFrame for display
        display_data = []
        for candidate in candidates:
            display_data.append({
                'Role Type': candidate.get('role type', ''),
                'FullName': candidate.get('full name', ''),
                'First Name': candidate.get('first name', ''),
                'Last Name': candidate.get('last name', ''),
                'Mobile': candidate.get('mobile', ''),
                'Email': candidate.get('email', ''),
                'Duration 1': candidate.get('duration 1', ''),
                'Job Title 1': candidate.get('job title 1', ''),
                'Company 1': candidate.get('company 1', ''),
                'Duration 2': candidate.get('duration 2', ''),
                'Job Title 2': candidate.get('job title 2', ''),
                'Company 2': candidate.get('company 2', ''),
                'Duration 3': candidate.get('duration 3', ''),
                'Job Title 3': candidate.get('job title 3', ''),
                'Company 3': candidate.get('company 3', ''),
                'Location': candidate.get('location', ''),
                'Source File': candidate.get('filename', ''),
            })

        df = pd.DataFrame(display_data)
        st.dataframe(df, use_container_width=True)


def check_credentials():
    claude_status = False
    
    try:
        # Check OpenRouter API key
        if "CLAUDE_SONNET_4_API_KEY" in st.secrets:
            claude_status = True
            
    except Exception as e:
        st.error(f"Error checking credentials: {str(e)}")
    
    return {
        'claude_status': claude_status
    }


def process_resumes(uploaded_files, country):
    if len(uploaded_files) > MAX_FILES_PER_BATCH:
        st.error(
            f"Processing blocked: more than {MAX_FILES_PER_BATCH} files ({len(uploaded_files)}). "
            "Reduce the batch size and try again."
        )
        return

    st.session_state[_key('processing_in_progress', country)] = True
    st.session_state[_key('processing_complete', country)] = False
    st.session_state[_key('processed_candidates', country)] = []
    
    try:
        # Initialize services
        with st.spinner("Initializing"):
            try:
                pdf_processor = PDFProcessor()
                word_processor = WordProcessor()
                text_processor = TextProcessor()
                ai_parser = AIParser(st.secrets["CLAUDE_SONNET_4_API_KEY"], country)
            except Exception as e:
                st.error(f"Error initializing services: {str(e)}")
                st.session_state[_key('processing_in_progress', country)] = False
                return
        
        # Progress tracking
        progress_container = st.container()
        with progress_container:
            progress_bar = st.progress(0)
            status_text = st.empty()
        
        # Archiving uploader (None when Azure is not configured → no-op archiving)
        uploader = get_blob_uploader()

        total_files = len(uploaded_files)
        successful_processes = 0
        
        for i, uploaded_file in enumerate(uploaded_files):
            try:
                current_progress = (i / total_files)
                progress_bar.progress(current_progress)
                status_text.text(f"Processing {uploaded_file.name}... ({i+1}/{total_files})")

                # Read bytes once (non-consuming) so we can archive and then let
                # the processors read the same upload independently.
                data = uploaded_file.getvalue()

                # Archive-first: upload to blob storage before extraction so the
                # permanent URL is available to attach to the parsed record.
                permanent_url = None
                blob_path = None
                if uploader is not None:
                    try:
                        permanent_url, blob_path = uploader.upsert(
                            data, uploaded_file.name, country
                        )
                    except Exception as upload_error:
                        # Fail-soft: keep parsing; Source File falls back to the
                        # original filename below.
                        st.warning(
                            f"Could not archive {uploaded_file.name}: {upload_error}"
                        )

                # Extract text based on file type
                file_extension = uploaded_file.name.lower().split('.')[-1]
                extracted_text = ""
                
                if file_extension == 'pdf':
                    with st.spinner(f"Extracting {uploaded_file.name}..."):
                        extracted_text = pdf_processor.process_pdf_file(uploaded_file)
                elif file_extension in ('docx', 'doc'):
                    with st.spinner(f"Extracting {uploaded_file.name}..."):
                        extracted_text = word_processor.process_word_file(uploaded_file)
                elif file_extension == 'txt':
                    with st.spinner(f"Reading {uploaded_file.name}..."):
                        extracted_text = text_processor.process_text_file(uploaded_file)
                else:
                    st.warning(f"Unsupported file type: {file_extension}")
                    continue
                
                if not extracted_text.strip():
                    st.warning(f"No text TO extract from {uploaded_file.name}")
                    continue
                
                # Parse resume using AI
                with st.spinner(f"Analyzing {uploaded_file.name}."):
                    parsed_data = ai_parser.parse_resume(extracted_text)
                
                # Source File = durable permanent blob URL when archived, else
                # fall back to the original filename (fail-soft / Azure off).
                parsed_data['filename'] = permanent_url or uploaded_file.name
                if blob_path:
                    parsed_data['blob_path'] = blob_path
                
                # Add to results
                st.session_state[_key('processed_candidates', country)].append(parsed_data)
                successful_processes += 1
                
                
            except Exception as e:
                st.error(f"Error processing {uploaded_file.name}: {str(e)}")
                continue
        
        # Final progress update
        progress_bar.progress(1.0)
        
        # Mark processing as complete
        st.session_state[_key('processing_complete', country)] = True
        st.session_state[_key('processing_in_progress', country)] = False
        
        if successful_processes > 0:
            st.success(f"Successfully processed {successful_processes}/{total_files} resume files.")
        else:
            st.warning(" No files were successfully processed.")
            
    except Exception as e:
        st.error(f"An unexpected error occurred: {str(e)}")
        st.session_state[_key('processing_in_progress', country)] = False
        # Show detailed error for debugging
        with st.expander("Error Details"):
            st.code(traceback.format_exc())


def generate_and_download_excel(country):
    """Generate and auto-download Excel report"""
    try:
        candidates = st.session_state[_key('processed_candidates', country)]
        if not candidates:
            st.warning("No candidate data to export.")
            return

        # Source File already holds the bare permanent blob URL (public),
        # so the Excel export uses the candidates as-is.
        with st.spinner("Generating Excel report..."):
            exporter = ExcelExporter()
            excel_data = exporter.export_candidates(candidates)

            # Encode to base64 for direct download
            b64 = base64.b64encode(excel_data).decode()
            filename = f"resume_analysis_{country}.xlsx"
            
            # Auto trigger download
            js = f"""
            <html>
            <head>
            <meta http-equiv="refresh" content="0; url=data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" />
            </head>
            <body>
            
            </body>
            </html>
            """
            st.components.v1.html(js, height=0)

    except Exception as e:
        st.error(f"Error generating Excel report: {str(e)}")
        with st.expander("Error Details"):
            st.code(traceback.format_exc())


if __name__ == "__main__":
    main()
