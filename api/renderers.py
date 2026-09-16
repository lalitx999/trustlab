# api/renderers.py
from rest_framework.renderers import JSONRenderer

class EnvelopedJSONRenderer(JSONRenderer):
    """
    Custom JSON renderer that automatically wraps DRF response data
    in a 'data' key to conform to the envelope pattern expected by the Next.js client.
    """
    def render(self, data, accepted_media_type=None, renderer_context=None):
        status_code = 200
        if renderer_context:
            response = renderer_context.get('response')
            if response:
                status_code = response.status_code

        # Wrap successful 2xx responses if they are not already enveloped
        if 200 <= status_code < 300:
            if isinstance(data, dict) and 'data' in data:
                # Already enveloped
                pass
            else:
                data = {'data': data}

        return super().render(data, accepted_media_type, renderer_context)
