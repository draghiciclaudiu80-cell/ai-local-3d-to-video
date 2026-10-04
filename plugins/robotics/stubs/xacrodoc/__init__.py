"""Stand-in for xacrodoc (ROS xacro files). The Robotics Toolbox imports it when it starts; the app only uses its
DH arm models, so this never has to work - it only says so if something tries."""


class XacroDoc:
    def __init__(self, *a, **k):
        raise RuntimeError("URDF / xacro robot models aren't installed in this app (DH models only)")


class _Packages:
    def __getattr__(self, name):
        raise RuntimeError("URDF / xacro robot models aren't installed in this app (DH models only)")


packages = _Packages()
