#!/bin/bash

# Step 1: Build the Angular module
ng build --prod > /dev/null 2>&1
RET=$?

if [[ $RET -ne 0 ]]; then
    echo "[!] Angular Build Failed: Run 'ng build --prod' to figure out why."
    exit 1
else
    echo "[*] Angular Build Succeeded"
fi

# Step 2: Copy the required files to the build output
MODULENAME=$(basename $PWD)
cp -r projects/$MODULENAME/src/module.svg dist/$MODULENAME/bundles/
cp -r projects/$MODULENAME/src/module.json dist/$MODULENAME/bundles/
cp -r projects/$MODULENAME/src/module.py dist/$MODULENAME/bundles/ > /dev/null 2>&1
cp -r projects/$MODULENAME/src/module.php dist/$MODULENAME/bundles/ > /dev/null 2>&1
cp -r projects/$MODULENAME/src/assets/ dist/$MODULENAME/bundles/ > /dev/null 2>&1

# Step 3: Clean up
rm -rf dist/$MODULENAME/bundles/*.map
rm -rf dist/$MODULENAME/bundles/*.min*
rm -rf bundletmp
mv dist/$MODULENAME/bundles/ bundletmp
rm -rf dist/$MODULENAME/*
mv bundletmp/* dist/$MODULENAME/
rm -rf bundletmp

# Step 4: Package (Optional)
if [[ $1 == "package" ]]; then
    VERS=$(cat dist/$MODULENAME/module.json | grep "version" | awk '{split($0, a, ": "); gsub("\"", "", a[2]); gsub(",", "", a[2]); print a[2]}')
    rm -rf $MODULENAME-$VERS.tar.gz
    echo "[*] Packaging $MODULENAME (Version $VERS)"
    cd dist/
    tar -pczf $MODULENAME-$VERS.tar.gz $MODULENAME
    mv $MODULENAME-$VERS.tar.gz ../
    cd ../
else
    echo "[*] Skipping Packaging (Run ./build.sh package to generate)"
fi
