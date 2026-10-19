# Run once in Krita Scripter: preserve the existing server, queue, and open documents.
import kritamcp
import importlib, sys
for name in ("stroke_data", "brush_controls", "geometry_data", "precision_tools"):
    module = sys.modules.get("kritamcp." + name)
    if module is not None:
        importlib.reload(module)
from pathlib import Path
from krita import Krita
source = Path(kritamcp.__file__).read_text()
source = source.rsplit('# Register the extension', 1)[0]
# Preserve the queue referenced by the running HTTP request handlers.
queue = kritamcp.command_queue
counter = kritamcp.command_counter
extension = next(e for e in Krita.instance().extensions() if type(e).__name__ == 'KritaMCPExtension')
exec(compile(source, kritamcp.__file__, 'exec'), kritamcp.__dict__)
kritamcp.command_queue = queue
kritamcp.command_counter = counter
extension.__class__ = kritamcp.KritaMCPExtension
# Existing HTTPServer keeps its request-handler class; switch it to the new handler.
extension.server_thread.server.RequestHandlerClass = kritamcp.PaintRequestHandler
print('Krita MCP bridge', kritamcp.BRIDGE_VERSION, 'loaded; paintings preserved')
