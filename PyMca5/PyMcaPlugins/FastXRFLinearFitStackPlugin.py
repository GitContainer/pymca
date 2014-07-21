#/*##########################################################################
# Copyright (C) 2004-2014 V.A. Sole, European Synchrotron Radiation Facility
#
# This file is part of the PyMca X-ray Fluorescence Toolkit developed at
# the ESRF by the Software group.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
#############################################################################*/
__author__ = "V.A. Sole - ESRF Data Analysis"
__contact__ = "sole@esrf.fr"
__license__ = "MIT"
__copyright__ = "European Synchrotron Radiation Facility, Grenoble, France"
"""

A Stack plugin is a module that will be automatically added to the PyMca stack windows
in order to perform user defined operations on the data stack.

These plugins will be compatible with any stack window that provides the functions:
    #data related
    getStackDataObject
    getStackData
    getStackInfo
    setStack

    #images related
    addImage
    removeImage
    replaceImage

    #mask related
    setSelectionMask
    getSelectionMask

    #displayed curves
    getActiveCurve
    getGraphXLimits
    getGraphYLimits

    #information method
    stackUpdated
    selectionMaskUpdated
"""
import sys
import os
import numpy
import time
from PyMca5 import StackPluginBase
from PyMca5.PyMcaPhysics import FastXRFLinearFit
from PyMca5.PyMcaGui import FastXRFLinearFitWindow
from PyMca5.PyMcaGui import CalculationThread
from PyMca5.PyMcaGui import StackPluginResultsWindow
from PyMca5.PyMcaGui import PyMca_Icons as PyMca_Icons
from PyMca5.PyMcaGui import PyMcaQt as qt
from PyMca5.PyMcaIO import ArraySave

DEBUG = 0

class FastXRFLinearFitStackPlugin(StackPluginBase.StackPluginBase):
    def __init__(self, stackWindow, **kw):
        StackPluginBase.DEBUG = DEBUG
        StackPluginBase.StackPluginBase.__init__(self, stackWindow, **kw)
        self.methodDict = {}
        function = self.calculate
        info = "Fit stack with current fit configuration"
        icon = PyMca_Icons.fit
        self.methodDict["Fit Stack"] =[function,
                                       info,
                                       icon]
        function = self._showWidget
        info = "Show last results"
        icon = PyMca_Icons.brushselect
        self.methodDict["Show"] =[function,
                                  info,
                                  icon]
        self.__methodKeys = ["Fit Stack", "Show"]
        self.configurationWidget = None
        self.fitInstance = None
        self._widget = None
        self.thread = None

    def stackUpdated(self):
        if DEBUG:
            print("FastXRFLinearFitStackPlugin.stackUpdated() called")
        self._widget = None

    def selectionMaskUpdated(self):
        if self._widget is None:
            return
        if self._widget.isHidden():
            return
        mask = self.getStackSelectionMask()
        self._widget.setSelectionMask(mask)

    def mySlot(self, ddict):
        if DEBUG:
            print("mySlot ", ddict['event'], ddict.keys())
        if ddict['event'] == "selectionMaskChanged":
            self.setStackSelectionMask(ddict['current'])
        elif ddict['event'] == "addImageClicked":
            self.addImage(ddict['image'], ddict['title'])
        elif ddict['event'] == "removeImageClicked":
            self.removeImage(ddict['title'])
        elif ddict['event'] == "replaceImageClicked":
            self.replaceImage(ddict['image'], ddict['title'])
        elif ddict['event'] == "resetSelection":
            self.setStackSelectionMask(None)

    #Methods implemented by the plugin
    def getMethods(self):
        if self._widget is None:
            return [self.__methodKeys[0]]
        else:
            return self.__methodKeys

    def getMethodToolTip(self, name):
        return self.methodDict[name][1]

    def getMethodPixmap(self, name):
        return self.methodDict[name][2]

    def applyMethod(self, name):
        return self.methodDict[name][0]()

    # The specific part
    def calculate(self):
        if self.configurationWidget is None:
            self.configurationWidget = \
                            FastXRFLinearFitWindow.FastXRFLinearFitDialog()
        ret = self.configurationWidget.exec_()
        if ret:
            self._executeFunctionAndParameters()

    def _executeFunctionAndParameters(self):
        self._parameters = self.configurationWidget.getParameters()
        self._widget = None
        if self.fitInstance is None:
            self.fitInstance = FastXRFLinearFit.FastXRFLinearFit()
        #self._fitConfigurationFile="E:\DATA\COTTE\CH1777\G4-4720eV-NOWEIGHT-Constant-batch.cfg"

        if DEBUG:
            self.thread = CalculationThread.CalculationThread(\
                            calculation_method=self.actualCalculation)
            self.thread.result = self.actualCalculation()
            self.threadFinished()
        else:
            self.thread = CalculationThread.CalculationThread(\
                            calculation_method=self.actualCalculation)
            #qt.QObject.connect(self.thread,
            #             qt.SIGNAL('finished()'),
            #             self.threadFinished)
            self.thread.start()
            message = "Please wait. Calculation going on."
            CalculationThread.waitingMessageDialog(self.thread,
                                parent=self.configurationWidget,
                                message=message)
            while self.thread.isRunning():
                time.sleep(2)
            self.threadFinished()

    def actualCalculation(self):
        activeCurve = self.getActiveCurve()
        if activeCurve is not None:
            x, spectrum, legend, info = activeCurve
        else:
            x = None
            spectrum = None
        if not self.isStackFinite():
            # one has to check for NaNs in the used region(s)
            # for the time being only in the global image
            # spatial_mask = numpy.isfinite(image_data)
            spatial_mask = numpy.isfinite(self.getStackOriginalImage())
        stack = self.getStackDataObject()
        fitConfigurationFile = self._parameters['configuration']
        concentrations = self._parameters['concentrations']
        self.fitInstance.setFitConfigurationFile(fitConfigurationFile)
        weightPolicy = self._parameters['weight_policy']
        if weightPolicy:
            # force calculation of the unnormalized sum spectrum
            spectrum = None
        if stack.x in [None, []]:
            x = None
        else:
            x = stack.x[0]
        result = self.fitInstance.fitMultipleSpectra(x=x,
                                                     y=stack,
                                                     weight=weightPolicy,
                                                     concentrations=concentrations,
                                                     ysum=spectrum)
        return result

    def threadFinished(self):
        result = self.thread.result
        self.thread = None
        if type(result) == type((1,)):
            #if we receive a tuple there was an error
            if len(result):
                if result[0] == "Exception":
                    # somehow this exception is not caught
                    raise Exception(result[1], result[2])
                    return
        if 'concentrations' in result:
            imageNames = result['names']
            images = numpy.concatenate((result['parameters'],
                                        result['concentrations']), axis=0)
        else:
            images = result['parameters']
            imageNames = result['names']
        nImages = images.shape[0]
        self._widget = StackPluginResultsWindow.StackPluginResultsWindow(\
                                        usetab=False)
        self._widget.buildAndConnectImageButtonBox()
        qt = StackPluginResultsWindow.qt
        self._widget.sigMaskImageWidgetSignal.connect(self.mySlot)
        self._widget.setStackPluginResults(images,
                                          image_names=imageNames)
        self._showWidget()

        # save to output directory
        parameters = self.configurationWidget.getParameters()
        outputDir = parameters["output_dir"]
        if outputDir in [None, ""]:
            if DEBUG:
                print("Nothing to be saved")
                return
        if parameters["file_root"] is None:
            fileRoot = ""
        else:
            fileRoot = parameters["file_root"].replace(" ","")
        if fileRoot in [None, ""]:
            fileRoot = "images"
        if not os.path.exists(outputDir):
            os.mkdir(outputDir)
        imagesDir = os.path.join(outputDir, "IMAGES")
        if not os.path.exists(imagesDir):
            os.mkdir(imagesDir)
        imageList = [None] * (nImages + len(result['uncertainties']))
        fileImageNames = [None] * (nImages + len(result['uncertainties']))
        j = 0
        for i in range(nImages):
            name = imageNames[i].replace(" ","-")
            fileImageNames[j] = name
            imageList[j] = images[i]
            j += 1
            if not imageNames[i].startswith("C("):
                # fitted parameter
                fileImageNames[j] = "s(%s)" % name
                imageList[j] = result['uncertainties'][i]
                j += 1
        fileName = os.path.join(imagesDir, fileRoot+".edf")
        ArraySave.save2DArrayListAsEDF(imageList, fileName,
                                       labels=fileImageNames)
        fileName = os.path.join(imagesDir, fileRoot+".csv")
        ArraySave.save2DArrayListAsASCII(imageList, fileName, csv=True,
                                         labels=fileImageNames)

    def _showWidget(self):
        if self._widget is None:
            return
        #Show
        self._widget.show()
        self._widget.raise_()

        #update
        self.selectionMaskUpdated()

MENU_TEXT = "Fast XRF Stack Fitting"
def getStackPluginInstance(stackWindow, **kw):
    ob = FastXRFLinearFitStackPlugin(stackWindow)
    return ob
