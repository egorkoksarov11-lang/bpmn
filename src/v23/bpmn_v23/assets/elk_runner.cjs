// Geometry-only adapter. Never parses or serializes the BPMN model.
const fs = require('fs');
const ELK = require(process.argv[2] || 'elkjs/lib/elk.bundled.js');
new ELK().layout(JSON.parse(fs.readFileSync(0, 'utf8')))
 .then(result => process.stdout.write(JSON.stringify(result)))
 .catch(error => { console.error(error.message); process.exit(1); });
