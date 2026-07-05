import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';

import { fromFrontendRoot } from './_paths.mjs';

const abilityModelsPageSource = readFileSync(
  fromFrontendRoot('src/app/admin/ability-models/page.tsx'),
  'utf8'
);

assert.match(
  abilityModelsPageSource,
  /const runtimeModelCandidateLabel = useCallback[\s\S]*modelProviderFilter\.trim\(\)[\s\S]*instance\.model_id\.trim\(\) \|\| runtimeModelRouteLabel\(instance\)/,
  'Filtered ability-model candidate rows must omit the repeated provider prefix and show the model id'
);

assert.match(
  abilityModelsPageSource,
  /activeDialogModelData\?\.filteredCandidates\.map[\s\S]*runtimeModelCandidateLabel\(instance\)/,
  'Ability-model candidate list must use the filtered candidate label'
);

assert.match(
  abilityModelsPageSource,
  /selected[\s\S]*runtimeModelRouteLabel\(selected\)/,
  'Selected primary and fallback summaries must keep the full provider/model route label'
);

console.log('admin_ability_models_dialog_contract: ok');
