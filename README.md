# Snipping-Tool-with-OCR
The program snips the screen and get text from area using OCR.

1. You have to install tesseract-ocr-w64-setup-v5.0.0-alpha.20200328.exe to run this program.

Please refer this: https://medium.com/quantrium-tech/installing-and-using-tesseract-4-on-windows-10-4f7930313f82

2. Please install miniconda (Python version: 3.8)

https://docs.conda.io/en/latest/miniconda.html

If you want to run program without installing miniconda, you can also use virtual environment in Python.

About how to use virtual environment in Python, please refer this:

https://packaging.python.org/guides/installing-using-pip-and-virtual-environments/

After creating virtual environment, you have to activate virtual environment.

```
Note 1: 
If you want to run program in the new device, you have to recreate virtual environment again.
Because each virtual environment include its own device information (for example: Path), so you have to delete virtual environment and recreate virtual environment again for a new device.
After creating virtual environment, please install needed python module using 'pip install' command

Note 2:
You have to install pyinstaller module to virtual environment to create exe file using pyinstaller command
```

3. Goto source code directory and run below command.
```
pip install -r requirements.txt
```
4. Run program using below command.
```
python app.py
```
5. You can change some parameters of app using config.yaml
```
      interval -> time between OCR operation per second

      max_trace -> max count of log

      debug mode -> dump ROI(region of interest) images
      
      screen_id -> ID of screen in multiple displays
      
      time_periods -> second of time periods
```    
6. You can make exe file using below command.
```
pyinstaller app.py --add-data L2-easy.ico;. --add-data alarm.mp3;. --add-data config.yaml;. --add-data tessdata;tessdata -w --clean -y --name L2-easy --icon=L2-easy.ico --windowed
```
7. How to make installer file

You can use Advanced Installer (https://www.advancedinstaller.com/?utm_source=adwords&utm_medium=paid&utm_campaign=advancedinstaller&gclid=EAIaIQobChMIgL3TgO-q7wIVFpayCh17BwBIEAAYASAAEgJmrfD_BwE)  to make installer file.

To make simple setting for installer file, you can use trial version of Advanced Installer

You have to copy `Tesseract-OCR` which installed in `C:\Program Files\Tesseract-ORC` and paste to the project folder when making installer file, so that Users don't need to install tesseract-ocr-w64-setup-v5.0.0.20211201.exe.

You have to set Envirionment Paths Variable in the Advanced Installer project file(*.aip) 
(https://ibb.co/k2kJk1Z)
