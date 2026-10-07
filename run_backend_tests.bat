@echo off
cd /d c:\Users\ASHWIN\Downloads\PROJECTS\MISTIQ\MISTIQ
python -m pytest -q --no-header > .testrun_backend.txt 2>&1
echo DONE >> .testrun_backend.txt
