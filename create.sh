#!/bin/bash

#  _    _       _    _____
# | |  | |     | |  | ____|
# | |__| | __ _| | _| |__
# |  __  |/ _` | |/ /___ \
# | |  | | (_| |   < ___) |
# |_|  |_|\__,_|_|\_\____/

MODULE_NAME="NOTSPECIFIED"
MODULE_TITLE="NOTSPECIFIED"
MODULE_AUTHOR="NOTSPECIFIED"
MODULE_DESC="NOTSPECIFIED"

print_banner() {
    echo " __          ___ ______ _   _____ _                              _       "
    echo " \ \        / (_)  ____(_) |  __ (_)                            | |      "
    echo "  \ \  /\  / / _| |__   _  | |__) | _ __   ___  __ _ _ __  _ __ | | ___  "
    echo "   \ \/  \/ / | |  __| | | |  ___/ | '_ \ / _ \/ _\` | '_ \| '_ \| |/ _ \ "
    echo "    \  /\  /  | | |    | | | |   | | | | |  __/ (_| | |_) | |_) | |  __/ "
    echo "     \/  \/   |_|_|    |_| |_|   |_|_| |_|\___|\__,_| .__/| .__/|_|\___| Mark 7"
    echo " Module Creation Helper                             | |   | |            "
    echo " Version 1.1                                        |_|   |_|            "
    echo " "
    echo " "
}

get_info() {
    read -p "[*] Module Name: " MODULE_NAME
    read -p "[*] Module Title: " MODULE_TITLE
    read -p "[*] Module Author: " MODULE_AUTHOR
    read -p "[*] Module Short Description: " MODULE_DESC

    sanitize_info
}

sanitize_info() {
    # Remove All Spaces from Module Name
    MODULE_NAME=${MODULE_NAME// /}
}

create_from_template() {
    if [[ ! -d "Misc/module-template" ]]; then
        echo "[!!] The template module seems to be missing. Please re-clone this repository and try again."
        exit 1
    fi

    echo "[*] Creating New Module ($MODULE_NAME)."

    cp -r Misc/module-template $MODULE_NAME

    grep -rl examplemodule $MODULE_NAME/ | xargs sed -i "s/examplemodule/$MODULE_NAME/g"
    grep -rl example-module $MODULE_NAME/ | xargs sed -i "s/example-module/$MODULE_NAME/g"
    grep -rl example-service $MODULE_NAME/ | xargs sed -i "s/example-service/$MODULE_NAME/g"
    grep -rl ExampleModuleComponent $MODULE_NAME/ | xargs sed -i "s/ExampleModuleComponent/${MODULE_NAME}Component/g"
    grep -rl ExampleServiceService $MODULE_NAME/ | xargs sed -i "s/ExampleServiceService/${MODULE_NAME}Service/g"
    grep -rl ExampleModuleModule $MODULE_NAME/ | xargs sed -i "s/ExampleModuleModule/${MODULE_NAME}Module/g"
    
    grep -rl "the Example Module!" $MODULE_NAME/ | xargs sed -i "s/the Example Module!/${MODULE_NAME}/g"
    grep -rl ": \"Example Module" $MODULE_NAME/ | xargs sed -i "s/: \"Example Module/: \"${MODULE_TITLE}/g"
    grep -rl "An example module!" $MODULE_NAME/ | xargs sed -i "s/An example module!/${MODULE_DESC}/g"
    grep -rl ": \"Hak5" $MODULE_NAME/ | xargs sed -i "s/: \"Hak5/: \"${MODULE_AUTHOR}/g"

    mv $MODULE_NAME/projects/examplemodule $MODULE_NAME/projects/$MODULE_NAME
    mv $MODULE_NAME/projects/$MODULE_NAME/src/lib/components/example-module.component.html $MODULE_NAME/projects/$MODULE_NAME/src/lib/components/$MODULE_NAME.component.html
    mv $MODULE_NAME/projects/$MODULE_NAME/src/lib/components/example-module.component.css $MODULE_NAME/projects/$MODULE_NAME/src/lib/components/$MODULE_NAME.component.css
    mv $MODULE_NAME/projects/$MODULE_NAME/src/lib/components/example-module.component.ts $MODULE_NAME/projects/$MODULE_NAME/src/lib/components/$MODULE_NAME.component.ts
    mv $MODULE_NAME/projects/$MODULE_NAME/src/lib/services/example-service.service.ts $MODULE_NAME/projects/$MODULE_NAME/src/lib/services/$MODULE_NAME.service.ts
    mv $MODULE_NAME/projects/$MODULE_NAME/src/lib/example-module.module.ts $MODULE_NAME/projects/$MODULE_NAME/src/lib/$MODULE_NAME.module.ts
}

ask_prepare_node() {
    while true; do
        read -p "[!] Would you like to prepare the Angular workspace? [Y/n] " yn
        case $yn in
            [Yy]* ) prepare_node; break;;
            [Nn]* ) return;;
            * ) prepare_node; break;;
        esac
    done
}

prepare_node() {
    echo "[*] Preparing the Angular workspace."
    cd $MODULE_NAME

    if ! command -v npm &> /dev/null; then
        echo "[!] NPM does not appear to be installed on this system. Failed to create workspace."
        return
    fi

    npm install
    echo "[*] Prepared the Angular workspace."
    cd -
}

finish() {
    echo "[*] A new module has been created! Exiting."
}

main() {
    print_banner
    get_info
    create_from_template
    ask_prepare_node

    finish
}

main

