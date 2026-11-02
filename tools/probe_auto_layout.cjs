// Optional external baseline only. Output is NOT accepted by the strict pipeline.
const fs = require('fs');
const path = require('path');
(async () => {
  const [source, output] = process.argv.slice(2);
  if (!source || !output || path.resolve(source) === path.resolve(output)) {
    throw new Error('Usage: node tools/probe_auto_layout.cjs INPUT.bpmn SEPARATE_OUTPUT.bpmn');
  }
  const { layoutProcess } = await import('bpmn-auto-layout');
  const result = await layoutProcess(fs.readFileSync(source, 'utf8'));
  const xml = typeof result === 'string' ? result : result.xml;
  if (typeof xml !== 'string') throw new Error('Unsupported library result');
  fs.writeFileSync(output, xml);
  process.stdout.write('External baseline written; semantic/DI verification still required.\n');
})().catch(error => { console.error(error.message); process.exit(1); });
