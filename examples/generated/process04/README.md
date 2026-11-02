# Process 04 — generated from scratch

The generated model retains all 69 nodes, 86 sequence flows, 71 information links, 18 information objects and 9 roles. All original business XML and existing DI identities are preserved. Document glyphs are standard pages; data stores remain cylinders.

The standard placement portfolio did not pass label and route checks. A wider semantic placement with scale 1.6 was independently verified. Scaling moves generated centres and lane envelopes while retaining measured glyph/text sizes; original coordinates are erased before planning.

Two generic fixes were needed: flow captions can use clear quarter points along a segment when its midpoint is busy; information links exceeding the eight-bend limit remain eligible for repair while already safe information links remain protected. No checks were relaxed.

131 tests passed in an isolated run (41.69 s), including a new congested-caption regression. An earlier concurrent run hit the unchanged v22 test's 20-second routing timeout. The 25-reference corpus was not rerun for these fixes; the r10 corpus report describes the preceding implementation.

Download `4_result.zip` for BPMN, SVG, the standard-document input and independent audits. Unzip and open `4.bpmn` in a BPMN editor, or `4.svg` in a browser. Reproduce after `npm ci` and installing Python requirements:

```bash
python tools/run_spaced_scratch.py --input path/to/4.bpmn --output-dir result --candidate-timeout 60
```

The selected cold run took 235.479 s. Business equality, full visible names, ports, clearance, label safety and the eight-bend limit pass. Line-to-line crossings may remain. Readable A4 printing and human-reference quality are not claimed.
