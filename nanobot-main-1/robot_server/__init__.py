"""Single-process HTTP composition root for the robot platform."""

from robot_server.app import RobotServerConfig, create_robot_server_app

__all__ = ("RobotServerConfig", "create_robot_server_app")
