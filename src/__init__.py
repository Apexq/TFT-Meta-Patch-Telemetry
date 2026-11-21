"""TFT Meta & Patch Intelligence Pipeline (Dynamic Active Set Support)."""

import os

TARGET_SET_NUMBER = int(os.environ.get("TFT_TARGET_SET_NUMBER", "18"))
TARGET_MUTATOR = f"TFTSet{TARGET_SET_NUMBER}"
