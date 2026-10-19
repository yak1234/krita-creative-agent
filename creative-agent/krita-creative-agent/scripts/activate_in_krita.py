"""Run in Krita's Scripter once after installation to activate without restarting."""
import kritamcp
from kritamcp.creative_tools import CreativeTools
from kritamcp.creative_docker import register_creative_docker
from kritamcp.creative_docker import CreativeAgentDocker
from krita import Krita
from PyQt5.QtCore import Qt

if not getattr(kritamcp, '_creative_hot_loaded', False):
    for name, method in CreativeTools.__dict__.items():
        if callable(method) and (name.startswith('_creative_') or name == 'cmd_creative'):
            setattr(kritamcp.KritaMCPExtension, name, method)
    original_execute = kritamcp.KritaMCPExtension.execute_command

    def execute_with_creative(self, command):
        if command.get('action') == 'creative':
            try:
                return self.cmd_creative(command.get('params', {}))
            except Exception as error:
                return {'error': str(error), 'error_code': 'creative_validation'}
        return original_execute(self, command)

    kritamcp.KritaMCPExtension.execute_command = execute_with_creative
    if 'creative' not in kritamcp.ALL_COMMANDS:
        kritamcp.ALL_COMMANDS.append('creative')
        register_creative_docker()
    kritamcp._creative_hot_loaded = True
    print('Creative Agent is ready in Settings → Dockers → Creative Agent.')

# Factories are instantiated when a Krita window is created. Add one to the
# already-open window too, so activation preserves unsaved documents.
if not getattr(kritamcp, '_creative_docker_instance', None):
    docker = CreativeAgentDocker()
    docker.setObjectName('krita_creative_agent')
    Krita.instance().activeWindow().qwindow().addDockWidget(Qt.RightDockWidgetArea, docker)
    kritamcp._creative_docker_instance = docker
kritamcp._creative_docker_instance.show()
