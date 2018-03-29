#!/bin/sh
mkdir build
cd build
cmake ..
make
cp meshpy_berkeley/meshrender.so ../meshpy_berkeley
cd ..
rm -rf build
