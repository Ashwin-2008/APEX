@echo off
cd /d c:\Users\ASHWIN\Downloads\PROJECTS\MISTIQ\MISTIQ\frontend
call npm test > ..\.testrun_frontend.txt 2>&1
echo DONE >> ..\.testrun_frontend.txt
