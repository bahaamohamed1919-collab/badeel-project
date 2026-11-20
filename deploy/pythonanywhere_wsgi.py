"""WSGI file for PythonAnywhere.

Copy everything below into the WSGI configuration file that PythonAnywhere
opens from the Web tab, and replace YOUR_USERNAME with your PythonAnywhere
username. Nothing secret goes in this file: the secret keys are created on
the server in instance/ and never leave it.
"""
import os
import sys

PROJECT = "/home/YOUR_USERNAME/badeel-project"
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

os.environ["BADEEL_HTTPS"] = "1"           # secure cookies: the site is served over HTTPS
os.environ["BADEEL_TRUST_PROXY"] = "1"     # PythonAnywhere puts a proxy in front of the site
os.environ["BADEEL_PUBLIC_NOTICE"] = "1"   # banner: trial version, not medical advice

from badeel import create_app  # noqa: E402

application = create_app()
