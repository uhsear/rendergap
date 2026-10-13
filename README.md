# rendergap

Flag the unique-value classes that carry a `<Null>` token, and the values that have no class and no default symbol, by counting the rows in the data.

A hazard-zone layer is drawn with unique values on two fields: a zone code and a sub-type. Most
zone rows have no sub-type, so that field is null. Pro writes the class for such a row with the
text `<Null>` in place of the value, so the class value reads `A,<Null>`.

The server draws those rows. A web map in a browser did not. Close to two in five of the layer's
pop-ups were gone, and nobody had changed a symbol. The fix was a renderer on the zone field alone.

The check everybody writes first does not see this. It lists the values in the data that no class
covers. Here every value has a class, so that list is empty and the layer reads as clean. The only
way to see the problem is to count the rows that sit in a class whose value carries the token.

A second gap sits next to it. A renderer with no default symbol assigns no symbol to a value it has
no class for. A value added by next month's load then draws nothing, and no error says so.

```
$ python rendergap.py --self-test
rendergap self-test: temporary files and 127.0.0.1 only, no credentials
--------------------------------------------------------------------
PASS  'A,<Null>' carries the token
...
PASS  a null-token class holding rows fails the run  <-- pinned defect
PASS  a plain unmatched-values diff finds nothing wrong with the null-token classes  <-- pinned defect
...
PASS  the query counts the object id field, grouped by the renderer fields  <-- pinned defect
...
PASS  a server that echoes the rejected token has it redacted from the error  <-- pinned defect
PASS  a redirect is refused and the second host never sees the request  <-- pinned defect
PASS  a JSON error body under HTTP 200 is an error, not a layer  <-- pinned defect
...
PASS  a response cut at the limit with nothing else flagged exits 4, never 0  <-- pinned defect
PASS  a layer with no rows compared nothing, so exit 4  <-- pinned defect
...
PASS  a unique prefix --ap of --apply is REFUSED by the parser and writes nothing  <-- pinned defect
...
PASS  the footer reports failures by count and by name, and exits 1  <-- pinned defect
PASS  importing the module prints nothing and exposes the core
--------------------------------------------------------------------
170 assertions, 0 failed
```

The full run prints all 170 assertions. Each `...` line above is where this block is cut.

## What already exists

ArcGIS Pro's `arcpy.mp` has a
[UniqueValueRenderer](https://doc.esri.com/en/arcgis-pro/latest/arcpy/mapping/uniquevaluerenderer-class.html)
class. Its `listMissingValues` method "provides a mechanism to identify values missing from a
unique value renderer". Use it when you work inside Pro and want the missing values. It runs in
Pro's Python. Its page describes a list of values. It does not mention a row count or the `<Null>`
token, and I did not run it, so I do not say what it returns for the layer in the story.

This tool differs in four ways. It needs no Pro and no project file. It asks the data how many rows
sit in each value combination. It flags a class that carries the token, even when the data matches
it. And it exits non-zero, so a scheduled job can read it.

Two tools by the same author are close but do not do this. `svcdrift` compares the renderer of one
service with another and never queries the data. `cimscan` lists the data sources in project and
layer files, and its diff compares the renderer field only, not the classes.

A search of GitHub on 2026-10-13 found one repository named `rendergap`. It is about light
transport in a game engine and has nothing to do with maps. Searches for a unique-value renderer
returned samples that build or read a renderer, such as `geolba/FeatureRenderer` and
`dmuthami/uniqueValueRenderer`. I found none that audits one. That shows only that the search found
nothing.

## Requirements

Python 3.9 or newer and nothing else. No `arcpy`, no third-party package. It reads a layer's REST
endpoint over HTTP or HTTPS, or two JSON files that you saved.

The self-test prints the same 170 assertions on Windows (Python 3.13.2), on Python 3.9.25, on
Python 3.10.20 and on Ubuntu (Python 3.12.3). The Windows and Ubuntu outputs are identical line for
line. `coverage run --branch rendergap.py --self-test` reports 100 percent of lines and branches on
Windows (coverage 7.16.1) and on Ubuntu (coverage 7.16.2). No line is excluded from the measurement.

The self-test starts a stub server on `127.0.0.1` with `http.server`. Every network path in this
README runs against that stub: the token header, the redirect, the error body under HTTP 200, a
response cut at the limit, and a refused connection. It never contacts another host.

```
git clone https://github.com/uhsear/rendergap.git
```

## Usage

Name a layer by its URL, or give it two saved files.

```
python rendergap.py --self-test
python rendergap.py --url https://host/arcgis/rest/services/Zones/MapServer/0
python rendergap.py --url https://host/arcgis/rest/services/Zones/FeatureServer/0 --token-env GIS_TOKEN
python rendergap.py --layer-json layer.json --stats-json stats.json
python rendergap.py --layer-json zones.lyrx --static
python rendergap.py --layer-json layer.json --stats-json stats.json --out findings.csv --apply
```

| Flag | Default | What it does |
|---|---|---|
| `--url` | none | A layer URL that ends in the layer number, with no query string. The tool reads `?f=json`, then runs one group-by query on `/query`. |
| `--layer-json` | none | A saved layer response, a `.lyrx` layer file, or a bare renderer. A byte order mark is accepted. |
| `--stats-json` | none | A saved group-by response. Its count column must be named `rendergap_n`. Needs `--layer-json`. |
| `--static` | off | Check the renderer alone. Needs `--layer-json`. Use it when you have no data. |
| `--token-env` | none | The name of an environment variable that holds a token. Needs `--url`. |
| `--fail-on-lint` | off | Count a lint as a failure. |
| `--sample` | `10` | How many findings to list under each heading. `0` lists none. |
| `--out` | off | Write the findings to this CSV. Needs `--apply`. |
| `--apply` | off | Actually write `--out`. Without it nothing is written. |
| `--self-test` | off | Run the assertions and exit. Other flags are ignored. |

Name exactly one of `--url` and `--layer-json`. With `--layer-json`, name exactly one of
`--stats-json` and `--static`. A mistake exits 64 and prints nothing on stdout.

Every flag must be spelled in full. The parser sets `allow_abbrev=False`. `--ap`, `--app` and
`--appl` are refused with exit 64 instead of being read as `--apply`, and `--sta` is not read as
`--static`. The self-test pins all three prefixes of the write flag.

`--out` must name a new file. A path that is also an input file is refused with exit 64, on a dry
run too. The tool sends only GET requests. `--out` is the only file it writes.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | The data was compared and nothing was flagged. Also a `--static` run with no finding. |
| 1 | At least one finding that can lose features. A lint counts only under `--fail-on-lint`. |
| 2 | A source could not be read, the service returned an error, or `--out` could not be written. |
| 4 | Nothing was compared. See below. |
| 64 | Usage error. |
| 70 | An unexpected crash in the tool. It is never a finding. |

Exit 4 covers a renderer this tool cannot compare, a response that the server cut at its record
limit, and a layer that has no rows. A scheduled job that reads 0 as "safe" must not get a 0 from a
run that compared nothing.

## What it checks

Take this synthetic layer. `layer.json` holds a two-field renderer with three classes and no
default symbol. `stats.json` holds the group-by response.

```
$ cat layer.json
{"name":"zones","objectIdField":"OBJECTID","drawingInfo":{"renderer":{"type":"uniqueValue","field1":"ZONE","field2":"SUBTYPE","fieldDelimiter":",","uniqueValueInfos":[{"value":"A,<Null>","label":"Zone A","symbol":{...}},{"value":"AE,<Null>","label":"Zone AE","symbol":{...}},{"value":"X,","label":"Zone X","symbol":{...}}]}}}
$ cat stats.json
{"features":[{"attributes":{"ZONE":"A","SUBTYPE":null,"rendergap_n":40}},{"attributes":{"ZONE":"AE","SUBTYPE":null,"rendergap_n":25}},{"attributes":{"ZONE":"X","SUBTYPE":"","rendergap_n":30}},{"attributes":{"ZONE":"B","SUBTYPE":"y","rendergap_n":5}}]}
$ python rendergap.py --layer-json layer.json --stats-json stats.json
rendergap: layer.json
renderer: unique value on ZONE, SUBTYPE, 3 class value(s), default symbol none
features: 100 in 4 value combination(s)

classes that carry the <Null> token: (2)
  class 'A,<Null>' (label 'Zone A'): 40 of 100 features (40.0%) are in it
  class 'AE,<Null>' (label 'Zone AE'): 25 of 100 features (25.0%) are in it

value combinations with no class and no default symbol: (1)
  'B,y': 5 feature(s) match no class and have no default symbol

VERDICT: 3 finding(s). The features in these groups may draw no symbol or lose their pop-up in a client.
```

The `...` inside `symbol` stands for a short symbol object that the demo leaves out of this page.

The tool reads each null in the data as the text `<Null>`, joins the values with the renderer's
delimiter, and compares the result with the class values as text. A null is not an empty string.
`X,` in the data is an empty sub-type, and it matches the class `X,`.

| Finding | Severity | What it means |
|---|---|---|
| `NULL_TOKEN` | FAIL when the class holds rows, or when rows are not counted | A class value has the token as one of its parts. This is the story. |
| `NULL_TOKEN` | LATENT | The same class, but no row is in it now. It fails the day a row arrives. |
| `HIDDEN` | FAIL | A value combination in the data has no class and the renderer has no default symbol. |
| `NO_DEFAULT` | LATENT | Every value read has a class, but a value added later would have no symbol. |
| `DEFAULTED` | INFO | A value combination has no class and the default symbol draws it. |
| `LINT_DEFAULT`, `LINT_EXPRESSION` | LINT | A layer file has an empty default symbol or an empty value expression. See below. |

A LATENT or INFO finding never changes the exit code.

### The plain diff reports this layer as clean

Remove the `B,y` row from `stats.json`. Every value in the data now has a class.

```
$ python rendergap.py --layer-json layer.json --stats-json stats-no-b.json
...
classes that carry the <Null> token: (2)
  class 'A,<Null>' (label 'Zone A'): 40 of 95 features (42.1%) are in it
  class 'AE,<Null>' (label 'Zone AE'): 25 of 95 features (26.3%) are in it
...
VERDICT: 2 finding(s). The features in these groups may draw no symbol or lose their pop-up in a client.
```

The self-test pins this. It runs the plain diff on this data, gets an empty list, and asserts that
the tool still exits 1.

### Check only, or write the findings

`--out` writes a CSV with the columns `kind`, `severity`, `key`, `rows` and `detail`. Without
`--apply` the tool says so and writes nothing.

```
$ python rendergap.py --layer-json layer.json --stats-json stats.json --out findings.csv
...
Check only. findings.csv was not written. Re-run with --apply.
$ python rendergap.py --layer-json layer.json --stats-json stats.json --out findings.csv --apply
...
wrote findings.csv
$ cat findings.csv
kind,severity,key,rows,detail
NULL_TOKEN,FAIL,"A,<Null>",40,"class 'A,<Null>' (label 'Zone A'): 40 of 100 features (40.0%) are in it"
NULL_TOKEN,FAIL,"AE,<Null>",25,"class 'AE,<Null>' (label 'Zone AE'): 25 of 100 features (25.0%) are in it"
HIDDEN,FAIL,"B,y",5,"'B,y': 5 feature(s) match no class and have no default symbol"
```

### A run on the renderer alone

`--static` reads the renderer and no data. It still fails on a class that carries the token, but it
cannot say how many rows are in it.

```
$ python rendergap.py --layer-json layer.json --static
...
data: not queried (--static)

classes that carry the <Null> token: (2)
  class 'A,<Null>' (label 'Zone A'): rows not counted, the data was not compared
...
```

A `--static` run with no finding exits 0, and its verdict says it was a static check.

## How it asks the data

`--url` sends two GET requests. The first reads the layer JSON. The second is a group-by statistics
query on the renderer's fields, with `where=1=1` and `returnGeometry=false`.

The statistic is a count of the layer's object-ID field, not of a renderer field. A SQL `COUNT` on
a column skips the nulls, so a count on the second renderer field would report zero rows for the
null class. The self-test stub counts like SQL. With the wrong field it reports the layer as clean,
and with the object-ID field it reports 40 of 100. Esri documents the skip for the geoprocessing
tool Summary Statistics, and I did not find it stated for the REST query. The object-ID field is
never null, so the question does not arise.

The tool finds the object-ID field from the layer's `objectIdField`, or else from the field whose
type is `esriFieldTypeOID`. If the layer names neither, the run exits 4.

### The token

`--token-env NAME` reads a token from the environment variable `NAME` and sends it in an
`X-Esri-Authorization: Bearer <token>` header. The token is never put in a URL. A `--url` that
carries a query string or a password is refused.

The tool sends the token only over `https`, or to a loopback address. It does not follow a redirect,
because a redirect would send the header to whatever host answers. If a server echoes the token
back in an error message, the tool replaces it with `***`.

The self-test proves each of these against the stub, and greps the output, the errors and the
findings file for the token.

## Layer files

`--layer-json` also reads a `.lyrx` layer file. Pro writes `fieldValues` as a list, so a null
appears as `<Null>` in the list. The tool joins the list with a comma. The file must hold exactly
one layer with a renderer.

I made a two-field unique-value layer with `arcpy` 3.6 and saved it as a layer file. I read these
facts from the file.

- The null class has `fieldValues` of `["A", "<Null>"]`, and its label is `A, <Null>`.
- An empty string is stored as `""`, so it stays apart from the null.
- The file has a `defaultSymbol` with a symbol and no `useDefaultSymbol` key. The arcpy object
  reports `useDefaultSymbol` as `False` for the same layer.

So Pro leaves out `useDefaultSymbol` while it is false. This tool draws a default symbol only when
the key is present and true. The Pro SDK says the property is "whether or not to use the default
symbol", and the arcpy page says it controls "the display of un-added values". Neither page says
what an absent key means, so this reading comes from the one file I made.

With group-by counts for that layer, the tool prints:

```
classes that carry the <Null> token: (1)
  class 'A,<Null>' (label 'A, <Null>'): 2 of 5 features (40.0%) are in it

no default symbol, so a value added later will have none: (1)
  the renderer has no default symbol. Every value combination read has a class.
```

### The lints

A layer file can carry a `defaultSymbol` that is null, or a symbol reference with no symbol. It can
also carry a `valueExpressionInfo` with an empty expression. The tool reports each as a lint.

These are lints, not findings. They come from one investigation in which a map service worker was
suspected of crashing on such a renderer. That investigation tested a hypothesis, and I have not
reproduced it. A lint does not change the exit code. `--fail-on-lint` makes it do so.

## Documentation checked

I read these pages on 2026-10-13. The status column says what each page supports.

| Behaviour the tool relies on | Status | Source |
|---|---|---|
| `groupByFieldsForStatistics` and `outStatistics` are query parameters. `returnGeometry` is a boolean. `exceededTransferLimit: false` means no more pages. | Documented | [Query (Feature Service/Layer)](https://developers.arcgis.com/rest/services-reference/enterprise/query-feature-service-layer/) |
| A unique-value renderer has `field1`, `field2`, `field3`, `fieldDelimiter`, `defaultSymbol`, `defaultLabel` and `uniqueValueInfos` with `value`. | Documented | [Renderer objects](https://developers.arcgis.com/rest/services-reference/enterprise/renderer-objects/) |
| A `defaultSymbol` of `null` assigns no symbol to an unmatched feature. The page also lists a known limitation: a generic symbol may show anyway. | Documented | [UniqueValueRenderer](https://developers.arcgis.com/javascript/latest/references/core/renderers/UniqueValueRenderer/) |
| The default delimiter is a comma when two fields are set. | Documented (JavaScript SDK) | The same page |
| A layer has `objectIdField` and fields of type `esriFieldTypeOID`. | Documented | [Feature layer](https://developers.arcgis.com/rest/services-reference/enterprise/layer-feature-service/) |
| Send a token in `X-Esri-Authorization` with the `Bearer` scheme, not in a query parameter. | Documented | [Accessing ArcGIS token-secured web services](https://enterprise.arcgis.com/en/server/11.1/administer/linux/accessing-arcgis-token-secured-web-services.htm) |
| `useDefaultSymbol` controls whether unmatched values are displayed. | Documented in one line | [arcpy.mp UniqueValueRenderer](https://doc.esri.com/en/arcgis-pro/latest/arcpy/mapping/uniquevaluerenderer-class.html), [CIMUniqueValueRenderer.UseDefaultSymbol](https://doc.esri.com/en/arcgis-pro/3.7/sdk/api-reference/topic6161.html) |
| `COUNT` skips nulls. | Documented for the Summary Statistics tool only | [Summary Statistics](https://desktop.arcgis.com/en/arcmap/10.5/tools/analysis-toolbox/summary-statistics.htm) |
| A browser client does not match a class value that contains `<Null>`. | Not documented. The renderer reference and the JavaScript reference do not mention the token. | Observed in one deployment |
| A service answers a bad request with a JSON `error` body and HTTP 200. | Not documented on the page I read | The tool treats an error body and an HTTP error status alike |
| A missing key means `useDefaultSymbol` is false in a layer file. | Not documented | One file made with `arcpy` 3.6 |

I tried to reproduce the browser behaviour with the ArcGIS Maps SDK for JavaScript in a headless
browser. The SDK did not load in that setup, so the claim in the story is unreproduced here. The
tool does not depend on it: it reports the class and the row count, and you decide.

## Run against a public service

The National Flood Hazard Layer is a public map service. Its flood-zone layer uses unique values on
`FLD_ZONE` and `ZONE_SUBTY` with the delimiter `;`, and it has classes such as `AE;<Null>`.

```
$ python rendergap.py --url https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28
rendergap: https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28
renderer: unique value on FLD_ZONE, ZONE_SUBTY, 106 class value(s), default symbol none
features: 5810855 in 69 value combination(s)

classes that carry the <Null> token: (9)
  class 'A;<Null>' (label '1% Annual Chance Flood Hazard'): 418129 of 5810855 features (7.2%) are in it
  class 'AE;<Null>' (label '1% Annual Chance Flood Hazard'): 833802 of 5810855 features (14.3%) are in it
  class 'AR;<Null>' (label '1% Annual Chance Flood Hazard'): no feature is in it now
...
value combinations with no class and no default symbol: (16)
  'X;AREA OF MINIMAL FLOOD HAZARD': 840340 feature(s) match no class and have no default symbol
  'OPEN WATER;<Null>': 759 feature(s) match no class and have no default symbol
...
VERDICT: 24 finding(s). The features in these groups may draw no symbol or lose their pop-up in a client.
```

The run took a few seconds on 2026-10-13, and the exit code was 1. One earlier attempt on the same
day ended with a connection reset, so the tool exited 2. I did not add a retry.

This shows that the tool runs end to end against a real service. It does not show that any client
drops these features. I tested no client against this layer, and the layer is not the one in the
story.

## Limits

- It reads a unique-value renderer only. A simple, class-breaks or Arcade-expression renderer exits 4.
- A renderer that stores its classes only in `uniqueValueGroups` exits 4. The tool reads `uniqueValueInfos`.
- A layer file with more than one renderer exits 4. Save one layer at a time.
- The comparison is exact text. Case and surrounding spaces count. A date field or a coded-value
  domain may show the value in a different form in the renderer than in the group-by response, and
  then every row would look unmatched. Check the first run by eye.
- Whole numbers match in either form, so `5` and `5.0` are one value. Other number formats are not normalised.
- The query uses `where=1=1` and sets no time or geometry filter. I did not test what a layer
  definition expression does to it.
- A response cut at the server's record limit exits 4. The tool does not page through grouped
  results. A layer with more value combinations than the limit needs a higher `maxRecordCount`.
- A group-by over a very large layer can be slow or refused by the service. The public layer above
  has about six million rows and answered in a few seconds. Your service may differ.
- There is no retry. A connection reset exits 2.
- The group-by response has to name each renderer field exactly as the renderer does.
- `NULL_TOKEN` is a risk, not a measured loss. The evidence is one deployment and one browser client.
- Nothing here checks a hosted layer's own client-side renderer in a web map. Save that JSON and use
  `--layer-json` with `--stats-json`.

## Contributing

Open an issue or pull request on GitHub.

## Author

Built by [Asir Khan](https://www.linkedin.com/in/asir-khan-310317264/).

## License

MIT.

## Related

Other single-file tools in this portfolio:

- [svcdrift](https://github.com/uhsear/svcdrift) - compares two services, renderer included, and never queries the data
- [cimscan](https://github.com/uhsear/cimscan) - lists the data sources in project and layer files
- [idreuse](https://github.com/uhsear/idreuse) - the same habit for a join: refuse the match the geometry disproves
- [restfake](https://github.com/uhsear/restfake) - a mock ArcGIS REST server that injects faults such as an error body under HTTP 200. The stub in this tool's self-test is smaller.
