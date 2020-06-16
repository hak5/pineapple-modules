#!/bin/bash

MODULE_NAME="RandomRoll"

cp -r examplemodule $MODULE_NAME
grep -rl examplemodule $MODULE_NAME/ | xargs sed -i "s/examplemodule/$MODULE_NAME/g"
grep -rl example-module $MODULE_NAME/ | xargs sed -i "s/example-module/$MODULE_NAME/g"
grep -rl example-service $MODULE_NAME/ | xargs sed -i "s/example-service/$MODULE_NAME/g"
grep -rl ExampleModuleComponent $MODULE_NAME/ | xargs sed -i "s/ExampleModuleComponent/${MODULE_NAME}Component/g"
grep -rl ExampleServiceService $MODULE_NAME/ | xargs sed -i "s/ExampleServiceService/${MODULE_NAME}Service/g"
grep -rl ExampleModuleModule $MODULE_NAME/ | xargs sed -i "s/ExampleModuleModule/${MODULE_NAME}Module/g"

grep -rl "the Example Module!" $MODULE_NAME/ | xargs sed -i "s/the Example Module!/${MODULE_NAME}/g"

mv $MODULE_NAME/projects/examplemodule $MODULE_NAME/projects/$MODULE_NAME
mv $MODULE_NAME/projects/$MODULE_NAME/src/lib/components/example-module.component.html $MODULE_NAME/projects/$MODULE_NAME/src/lib/components/$MODULE_NAME.component.html
mv $MODULE_NAME/projects/$MODULE_NAME/src/lib/components/example-module.component.css $MODULE_NAME/projects/$MODULE_NAME/src/lib/components/$MODULE_NAME.component.css
mv $MODULE_NAME/projects/$MODULE_NAME/src/lib/components/example-module.component.ts $MODULE_NAME/projects/$MODULE_NAME/src/lib/components/$MODULE_NAME.component.ts
mv $MODULE_NAME/projects/$MODULE_NAME/src/lib/services/example-service.service.ts $MODULE_NAME/projects/$MODULE_NAME/src/lib/services/$MODULE_NAME.service.ts
mv $MODULE_NAME/projects/$MODULE_NAME/src/lib/example-module.module.ts $MODULE_NAME/projects/$MODULE_NAME/src/lib/$MODULE_NAME.module.ts
