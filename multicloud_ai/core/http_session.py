"""HTTP sessions with isolated operating-system certificate trust."""
import requests

def system_trust_session():
    """Use Windows trust roots only for this session; never patch global SSL."""
    import ssl
    try:
        import truststore
        context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        context = ssl.create_default_context()

    class SystemTrustAdapter(requests.adapters.HTTPAdapter):
        def build_connection_pool_key_attributes(self, request, verify, cert=None):
            host, pool = super().build_connection_pool_key_attributes(request, verify, cert)
            if verify is True:
                pool['ssl_context'] = context
            return host, pool

    session = requests.Session()
    session.mount('https://', SystemTrustAdapter())
    return session

