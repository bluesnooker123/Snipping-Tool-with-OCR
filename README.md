# Snipping-Tool-with-OCR
The program snips the screen and get text from area using OCR.

1. You have to install tesseract-ocr-w64-setup-v5.0.0-alpha.20200328.exe to run this program
Please refer this: https://medium.com/quantrium-tech/installing-and-using-tesseract-4-on-windows-10-4f7930313f82

2. Please install miniconda (Python version: 3.8)
https://docs.conda.io/en/latest/miniconda.html

3. Goto source code directory and run below command
pip install -r modules.txt

4. Run program using below command
python main.py

5. You can change some parameters of app using config.yaml

      interval -> time between OCR operation per second

      max_trace -> max count of log

      debug mode -> dump ROI(region of interest) images
      
      time_periods -> second of time periods
      
6. You can make exe file using below command.( For version 8.0 which include Cryptlex)
pyinstaller main.py -w --add-data config.yaml;. --add-data tessdata/;tessdata/ --add-data product_v5b67c9c8-4094-4f55-b3d3-fd1227899e1a.dat;. --add-data LexActivator.dll;. --clean -y
      
