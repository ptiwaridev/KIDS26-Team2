"""Streamlit entrypoint for the clinical data RAG assistant.

Placeholder chat UI — wire up the agent router (SQL / RAG / both) here.
"""
import os

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Clinical Data Assistant", page_icon="🩺")
st.title("Clinical Data Assistant")

if os.getenv("USE_SYNTHETIC_DATA", "true").lower() == "true":
    st.info("Running against synthetic data.")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask a question about the patient cohort..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        response = "Agent routing (SQL / RAG / both) not yet wired up."
        st.markdown(response)
    st.session_state.messages.append({"role": "assistant", "content": response})
