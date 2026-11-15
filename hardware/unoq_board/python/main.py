"""Placeholder so the Arduino app tooling can build and flash ../sketch.

The real Linux-side program is hardware/unoq_bridge.py. It runs outside the app container
because the container cannot reach the backend on 127.0.0.1:8000.
"""
from arduino.app_utils import App

App.run()
