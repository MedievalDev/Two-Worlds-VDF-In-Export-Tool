@echo off
title TW1 OBJ-to-VDF Converter v1.0
python "%~dp0tw1_obj_to_vdf.py" %*
if errorlevel 1 pause
