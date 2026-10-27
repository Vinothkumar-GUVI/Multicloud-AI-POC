"""Optional OIDC gate for shared deployments; local mode remains available."""
import os
import streamlit as st


def require_login():
    if os.getenv('MULTICLOUD_REQUIRE_LOGIN', '').lower() not in {'1', 'true'}:
        return
    try:
        configured = bool(st.secrets.get('auth'))
    except (FileNotFoundError, KeyError):
        configured = False
    if not configured:
        st.error('Login is required but OIDC is not configured in .streamlit/secrets.toml.')
        st.stop()
    if not st.user.is_logged_in:
        st.info('Sign in to access the migration assessment.')
        if st.button('Sign in', key='oidc_sign_in'):
            st.login()
        st.stop()
    if st.sidebar.button('Sign out', key='oidc_sign_out'):
        st.session_state.clear()
        st.logout()
        st.stop()
