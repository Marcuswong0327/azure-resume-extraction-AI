import os
import traceback
from datetime import datetime, timedelta, timezone as _tz

import streamlit as st
import pandas as pd
from pdf_processor import PDFProcessor
from word_processor import WordProcessor
from text_processor import TextProcessor
from ai_parser import AIParser
from excel_exporter import ExcelExporter
from blob_uploader import BlobUploader
from config import get_secret
import cosmos_store
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
        return BlobUploader.from_settings()
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

    ALL_TABS = COUNTRIES + ["Global Search"]

    # CSS: make st.radio look identical to Streamlit's native tab bar
    st.markdown("""
    <style>
    div[data-testid="stRadio"] > label { display: none; }
    div[data-testid="stRadio"] > div {
        display: flex !important;
        flex-direction: row !important;
        gap: 0 !important;
        border-bottom: 1px solid rgba(250,250,250,0.2);
        padding-bottom: 0;
        margin-bottom: 1rem;
    }
    div[data-testid="stRadio"] label {
        padding: 8px 16px !important;
        cursor: pointer;
        font-size: 14px;
        font-weight: 400;
        color: rgba(250,250,250,0.6);
        border-bottom: 2px solid transparent;
        margin-bottom: -1px;
        background: none !important;
    }
    div[data-testid="stRadio"] label:has(input:checked) {
        color: #ff4b4b !important;
        border-bottom: 2px solid #ff4b4b !important;
        font-weight: 600;
    }
    div[data-testid="stRadio"] label > div:first-child { display: none; }
    </style>
    """, unsafe_allow_html=True)

    active = st.radio(
        "tab_nav",
        options=ALL_TABS,
        horizontal=True,
        label_visibility="collapsed",
        key="active_tab",
    )

    if active in COUNTRIES:
        render_country_tab(active, credentials_status)
    else:
        render_global_search_tab()


def render_global_search_tab():
    """Search all archived candidates stored in Azure Cosmos DB."""
    st.header("🔍 Global Candidate Search")

    if not cosmos_store.is_configured():
        st.warning(
            "Cosmos DB is not configured. Add **COSMOS_ENDPOINT** and **COSMOS_KEY** "
            "to your environment variables or `.streamlit/secrets.toml`, then restart the app."
        )
        return

    # ── Controls ──────────────────────────────────────────────────────────────
    query = st.text_input(
        "Search candidates",
        placeholder="E.g. sales consultant OR account executive",
        key="global_search_query",
    )
    st.caption('Supports **AND**, **OR**, **NOT** and **"quoted phrases"**. Plain words = AND.')

    col_filter, col_refresh = st.columns([3, 1])
    with col_filter:
        date_filter = st.selectbox(
            "Date filter",
            options=["All time", "Today", "Yesterday", "Last 3 days", "Last 7 days", "Last 30 days"],
            index=0,
            key="global_search_date_filter",
            label_visibility="collapsed",
        )
    with col_refresh:
        if st.button("🔄 Refresh", key="global_search_refresh", use_container_width=True):
            cosmos_store.clear_cache()

    # ── Load data ─────────────────────────────────────────────────────────────
    try:
        df = cosmos_store.load_candidates()
    except Exception as e:
        st.error(f"Could not load data from Cosmos DB: {str(e)}")
        with st.expander("Error Details"):
            st.code(traceback.format_exc())
        return

    if df.empty:
        st.info(f"No records found in Cosmos DB container `{cosmos_store.get_container_name()}`.")
        return

    # ── Date filter ───────────────────────────────────────────────────────────
    if date_filter != "All time" and "processed_at" in df.columns:
        now = datetime.now(_tz.utc)
        cutoffs = {
            "Today":        now.replace(hour=0, minute=0, second=0, microsecond=0),
            "Yesterday":    (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0),
            "Last 3 days":  now - timedelta(days=3),
            "Last 7 days":  now - timedelta(days=7),
            "Last 30 days": now - timedelta(days=30),
        }
        cutoff = cutoffs[date_filter]
        parsed_dates = pd.to_datetime(df["processed_at"], utc=True, errors="coerce")
        if date_filter == "Yesterday":
            mask = (parsed_dates >= cutoff) & (parsed_dates < cutoff + timedelta(days=1))
        else:
            mask = parsed_dates >= cutoff
        df = df[mask]

    # ── Boolean search ────────────────────────────────────────────────────────
    results = cosmos_store.search_candidates(df, query) if query.strip() else df

    # ── Results ───────────────────────────────────────────────────────────────
    label = (
        f"{len(results)} of {len(df)} candidate(s) match **\"{query}\"**"
        if query.strip()
        else f"**{len(results)}** candidate(s)"
    )
    if date_filter != "All time":
        label += f" — {date_filter}"
    st.caption(label)

    if results.empty:
        st.info("No candidates match your search.")
    else:
        _HIDDEN_COLS = {"id", "blob_path", "_rid", "_self", "_etag", "_attachments", "_ts"}
        display_cols = [c for c in results.columns if c not in _HIDDEN_COLS]
        priority = [c for c in ("processed_at", "country") if c in display_cols]
        ordered_cols = priority + [c for c in display_cols if c not in priority]
        st.dataframe(results[ordered_cols], use_container_width=True, hide_index=True)


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
            st.success(f"{len(uploaded_files)} file(s) uploaded successfully")

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
    claude_status = bool(get_secret("CLAUDE_SONNET_4_API_KEY"))

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
                api_key = get_secret("CLAUDE_SONNET_4_API_KEY")
                if not api_key:
                    st.error("CLAUDE_SONNET_4_API_KEY is not configured.")
                    st.session_state[_key('processing_in_progress', country)] = False
                    return
                ai_parser = AIParser(api_key, country)
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

                data = uploaded_file.getvalue()

                # Archive-first: upload to blob storage before extraction
                permanent_url = None
                blob_path = None
                if uploader is not None:
                    try:
                        permanent_url, blob_path = uploader.upsert(
                            data, uploaded_file.name, country
                        )
                    except Exception as upload_error: #fallback use fileName
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
                

                parsed_data['filename'] = permanent_url or uploaded_file.name
                if blob_path:
                    parsed_data['blob_path'] = blob_path
                else:
                    parsed_data['blob_path'] = f"{country}/local/{uploaded_file.name}"

                # Add to results
                st.session_state[_key('processed_candidates', country)].append(parsed_data)
                successful_processes += 1

                if cosmos_store.is_configured():
                    try:
                        save_error = cosmos_store.save_candidate(parsed_data, country)
                        if save_error:
                            st.warning(
                                f"Processed {uploaded_file.name} but could not save to "
                                f"Cosmos DB: {save_error}"
                            )
                    except Exception as save_exc:
                        st.warning(
                            f"Processed {uploaded_file.name} but could not save to "
                            f"Cosmos DB: {save_exc}"
                        )
                
                
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

        with st.spinner("Generating Excel report..."):
            exporter = ExcelExporter()
            excel_data = exporter.export_candidates(candidates)

        
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
