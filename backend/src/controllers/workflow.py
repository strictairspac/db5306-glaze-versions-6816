from starlette.responses import Response

from src.config.settings import engine
from src.services.workflow import signed_document
from src.utils.encoding import canonical


def download(identity, actor):
    document = signed_document(identity, actor)
    return Response(canonical(document), media_type='application/json', headers={
        'Content-Disposition': f'attachment; filename="evidence-{identity}.json"',
        'Cache-Control': 'no-store'})
