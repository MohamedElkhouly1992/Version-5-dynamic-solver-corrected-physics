from __future__ import annotations
import importlib
import platform
import sys

mods=["streamlit","numpy","pandas","scipy","sklearn","SALib","pyarrow","matplotlib","plotly","openpyxl","xlsxwriter","networkx","shap"]
print("Python:",sys.version.replace("\n"," "))
print("Executable:",sys.executable)
print("Platform:",platform.platform())
failed=[]
for m in mods:
    try:
        mod=importlib.import_module(m)
        print(f"{m:14s}: OK  {getattr(mod,'__version__','')}")
    except Exception as exc:
        failed.append((m,str(exc))); print(f"{m:14s}: FAIL {exc}")
if failed:
    raise SystemExit("PRECHECK FAILED: "+repr(failed))
print("PRECHECK PASSED")
