"""Simulation must start without importing the optional ZMotion plugin."""

from __future__ import annotations

import subprocess
import sys


def test_simulation_backend_does_not_load_zmotion_plugin_modules() -> None:
    probe = """
import sys
from robot_platform.backends.factory import RobotBackendConfig, create_robot_backend
backend = create_robot_backend(RobotBackendConfig(mode='simulation'))
assert backend.get_state().mode == 'idle'
print(','.join(sorted(name for name in sys.modules if name.startswith('robot_platform.backends.zmotion'))))
"""

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == ""


def test_robot_server_composition_uses_simulation_without_zmotion_modules() -> None:
    probe = """
import sys
import tempfile
from pathlib import Path
from robot_server.app import RobotServerConfig, create_robot_server_app
app = create_robot_server_app(config=RobotServerConfig(robot_data_dir=Path(tempfile.mkdtemp())))
assert app is not None
print(','.join(sorted(name for name in sys.modules if name.startswith('robot_platform.backends.zmotion'))))
"""

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == ""


def test_simulation_system_action_executes_without_loading_zmotion_modules() -> None:
    probe = """
import sys
from robot_platform.application import AuthenticatedPrincipal
from robot_platform.backends.emergency_stop import ProductEmergencyStopAdapter
from robot_platform.backends.factory import RobotBackendConfig

result = ProductEmergencyStopAdapter(
    config=RobotBackendConfig(mode='simulation')
).emergency_stop(
    AuthenticatedPrincipal('operator', 'operator', 'session', 'test')
)
assert result['ok'] is True
assert result['state'] == 'simulated_system_action_completed'
assert result['data']['action'] == 'emergency_stop'
print(','.join(sorted(name for name in sys.modules if name.startswith('robot_platform.backends.zmotion'))))
"""

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == ""
