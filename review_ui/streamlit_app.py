import os

import requests
import streamlit as st


API_BASE = os.getenv("REVIEW_API_BASE", "http://api:8000/api/v1")

st.set_page_config(page_title="Document Review Queue", layout="wide")
st.title("Document Intelligence Review Queue")

queue_response = requests.get(f"{API_BASE}/reviews/queue", timeout=10)
queue_response.raise_for_status()
tasks = queue_response.json()

if not tasks:
    st.info("No pending review tasks.")
else:
    selected = st.selectbox(
        "Pending tasks",
        options=tasks,
        format_func=lambda item: f"{item['document_id']} :: {item['field_name']} :: {item['confidence']}",
    )
    st.subheader("Task Details")
    st.json(selected)
    corrected = st.text_input("Corrected value", value=str(selected["proposed_value"].get("value", "")))
    reviewer_name = st.text_input("Reviewer name", value="analyst")
    comment = st.text_area("Comment")
    if st.button("Submit correction"):
        payload = {
            "reviewer_name": reviewer_name,
            "corrected_value": {"value": corrected},
            "comment": comment or None,
        }
        response = requests.post(
            f"{API_BASE}/reviews/{selected['id']}/decision",
            json=payload,
            timeout=10,
        )
        if response.ok:
            st.success("Correction submitted.")
        else:
            st.error(response.text)

