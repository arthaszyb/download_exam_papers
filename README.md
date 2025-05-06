# download_examp_papers
## Description
This script is to download the PDF examp papers from the Singapore testpapersfree website automantically. Thank to this website.

## Before running it
1. Modify the key parameters to fulfill your indivicial requirement is necessary.
* __grade__: Which of the academy grade to choose.
* __year_list__: The time period you'd like to have. Should be a list.
* __subject_choose__: The exam subject with only single choise.
* __stage_choose__: The exam type to choose.

2. Adjust the HOME path in __pyvenv.cfg__ file.

## How to execute it
The code can run independently with virtul env included. Run the script by commands below:\
`
nohup bin/python main.py >/dev/null &
`


