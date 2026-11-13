# rendergap

Flag the unique-value classes that carry a `<Null>` token, and the values that have no class and no default symbol, by counting the rows in the data.

A hazard-zone layer is drawn with unique values on two fields: a zone code and a sub-type. Most
zone rows have no sub-type, so that field is null. Pro writes the class for such a row with the
text `<Null>` in place of the value, so the class value reads `A,<Null>`.

The server draws those rows. A web map in a browser did not. Close to two in five of the layer's
pop-ups were gone, and nobody had changed a symbol. The fix was a renderer on the zone field alone.

The obvious check does not see this. It lists the values in the data that no class
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
PASS  a plain unmatched-values diff finds nothing wrong where every value has a class, and the run still exits 1  <-- pinned defect
...
PASS  the verdict names the latent null-token classes and does not say the layer carries none  <-- pinned defect
PASS  a renderer with an Arcade valueExpression is unsupported even when it names fields  <-- pinned defect
PASS  a layer file whose class values cannot be read is unsupported, not clean  <-- pinned defect
...
PASS  the query counts the object id field, grouped by the renderer fields  <-- pinned defect
...
PASS  a -5 in the data is written as '-5,x through --apply, and the count stays 3  <-- pinned defect
...
PASS  a trailing space exits 64 with a usage message, not 70  <-- pinned defect
...
PASS  the stub counts like SQL, so a count on a nullable field returns 0 for the 40 null rows, and the run refuses that instead of reporting the layer clean  <-- pinned defect
...
PASS  a response cut below the layer's own row count with no flag exits 4, never a clean 0  <-- pinned defect
...
PASS  a token with a trailing line break is stripped and sent clean  <-- pinned defect
...
PASS  a 460 character token that the server echoes is redacted whole, not cut at 200 first  <-- pinned defect
PASS  an unexpected crash exits 70 and redacts the token from its message and its traceback  <-- pinned defect
PASS  a renderer type that echoes the token is redacted from the NOT CHECKED verdict  <-- pinned defect
PASS  a class label that echoes the token is redacted from the report and the findings file  <-- pinned defect
PASS  a token typed into the --out path is redacted from the path line, exit 1  <-- pinned defect
...
PASS  a redirect is refused and the second host never sees the request  <-- pinned defect
PASS  a JSON error body under HTTP 200 is an error, not a layer  <-- pinned defect
...
PASS  a chunked reply cut in the middle exits 2, not 70  <-- pinned defect
...
PASS  a response cut at the limit with nothing else flagged exits 4, never 0  <-- pinned defect
PASS  a layer with no rows compared nothing, so exit 4  <-- pinned defect
...
PASS  --static on a clean renderer exits 4, not a clean 0  <-- pinned defect
PASS  a NOT CHECKED run writes no --out file even under --apply, and says so  <-- pinned defect
PASS  an unsupported renderer writes no --out file and says so  <-- pinned defect
PASS  an unrecognized argument is counted, never echoed  <-- pinned defect
PASS  an unrecognized argument is counted, never echoed  <-- pinned defect
...
PASS  a response as long as maxRecordCount with no exceededTransferLimit exits 4, never a clean 0  <-- pinned defect
...
PASS  a latent null-token class with no maxRecordCount to check the response against is not reported clean  <-- pinned defect
...
PASS  a class 5.0,<Null> that holds rows fails with its row count, not as an unverified latent class  <-- pinned defect
...
PASS  a hand-built statistics file with a zero count is refused, not read as an empty null class  <-- pinned defect
PASS  classes held only in uniqueValueGroups exit 4, never a clean 0  <-- pinned defect
...
PASS  a token pasted where the variable name goes is never echoed in the usage error  <-- pinned defect
PASS  an existing --out file is refused under --apply and keeps its content  <-- pinned defect
...
PASS  a unique prefix --ap of --apply is REFUSED by the parser and writes nothing  <-- pinned defect
...
PASS  the footer reports failures by count and by name, and exits 1  <-- pinned defect
PASS  importing the module prints nothing and exposes the core
--------------------------------------------------------------------
287 assertions, 0 failed
```

The full run prints all 287 assertions. Each `...` line above is where this block is cut. Every
other line is copied from the run.

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

Two tools by the same author are close but do not do this. `svcdrift` compares a published service
with the dataset it was published from, or with another service, and reports renderer class
differences such as a removed class. Its `--probe` flag reads one row to test the fields a service
advertises. It does not count the rows in each class and does not look for the `<Null>` token.
`cimscan` lists the data sources in project and layer files, and its diff compares the renderer
field only, not the classes.

On 2026-10-13, `gh search repos rendergap` returned two repositories: this one, and one other,
`yurij-maruda/RenderGap`. That one is about light transport in a game engine and has nothing to do
with maps. Searches for a unique-value renderer returned samples that build or read a renderer, such
as `geolba/FeatureRenderer` and `dmuthami/uniqueValueRenderer`. I found none that audits one. That
shows only that the search found nothing.

## Requirements

Python 3.9 or newer and nothing else. No `arcpy`, no third-party package. It reads a layer's REST
endpoint over HTTP or HTTPS, or two JSON files that you saved.

The self-test prints the same 287 assertions on Windows (Python 3.13.2 and 3.9.25) and on Ubuntu
(Python 3.9.25, 3.11.16 and 3.12.3). The Windows 3.13.2 and Ubuntu 3.12.3 outputs are identical line for line after
the carriage returns are removed. `coverage run --branch rendergap.py --self-test` reports 100
percent of statements and branches (1242 statements, 294 branches, none partial) on Windows (coverage
7.16.1). No line is excluded from the measurement. The system Ubuntu Python has no `coverage` or `pyflakes` module. In a venv on the same host,
Ubuntu 3.12.3 also reports 100 percent branch coverage (1242 statements, 294 branches, none
partial) and a clean pyflakes run.

The self-test starts a stub server on `127.0.0.1` with `http.server`. Every network path in this
README, except the dated public-service run, runs against that stub: the token header, the redirect,
the error body under HTTP 200, a response cut at the limit, and a refused connection. The self-test never contacts another host. The
"Run against a public service" section is a live run that you start yourself, and the self-test does not exercise it.

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
| `--url` | none | A layer URL that ends in the layer number, with no query string. The tool reads `?f=json`, then runs a group-by query on `/query`, and a row-count query only when the response is complete: not cut, not empty, not unverified, and shorter than the layer's `maxRecordCount`. |
| `--layer-json` | none | A saved layer response, a `.lyrx` layer file, or a bare renderer. A byte order mark is accepted. |
| `--stats-json` | none | A saved group-by response. Its count column must be named `rendergap_n`, and it must count the object id field. Needs `--layer-json`. |
| `--static` | off | Check the renderer alone. Needs `--layer-json`. Use it when you have no data. |
| `--token-env` | none | The name of an environment variable that holds a token. Needs `--url`. |
| `--fail-on-lint` | off | Count a lint as a failure. |
| `--sample` | `10` | How many findings to list under each heading. `0` lists none. |
| `--out` | off | Write the findings to this CSV. The path must not exist. Needs `--apply`. |
| `--apply` | off | Actually write `--out`. Without it nothing is written. |
| `--self-test` | off | Run the assertions and exit. Other known flags are ignored; an unknown flag still exits 64. |

Name exactly one of `--url` and `--layer-json`. With `--layer-json`, name exactly one of
`--stats-json` and `--static`. A mistake exits 64 and prints nothing on stdout.

Every flag must be spelled in full. The parser sets `allow_abbrev=False`. `--ap`, `--app` and
`--appl` are refused with exit 64 instead of being read as `--apply`, and `--sta` is not read as
`--static`. The self-test pins all three prefixes of the write flag.

`--out` must name a path that does not exist. Any existing path, an input file included, is refused
with exit 64, on a dry run too. A job that runs every night names a dated file, or removes the old
one first. A write that fails part-way removes the partial file. The tool sends only GET requests.
`--out` is the only file it writes. `--self-test` also writes in a temporary directory and removes
it.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | The data was compared and nothing was flagged. |
| 1 | At least one finding that can lose features. A lint counts only under `--fail-on-lint`. |
| 2 | A source could not be read, the service returned an error, or `--out` could not be written. |
| 4 | Nothing was compared, or the comparison could not be trusted. See below. |
| 64 | Usage error. |
| 70 | An unexpected crash in the tool. It is never a finding. |

Exit 4 covers a renderer this tool cannot compare, a response that the server cut at its record
limit, a layer that has no rows, a group-by whose counts do not add up to the layer's own row count, and a `--static` run with no finding. That includes a renderer with no `uniqueValueInfos` entries,
such as one that keeps its classes only in `uniqueValueGroups`. A scheduled job that reads 0 as
"safe" must not get a 0 from a run that compared nothing.

A `--static` run never exits 0, because it looked at no data. A cut response or an empty layer
exits 4 only when no class carries the token. If a class does, the
run exits 1 with "rows not counted", because the class is a risk whether or not the rows were
counted.

## What it checks

Take this synthetic layer. `layer.json` holds a two-field renderer with three classes and no
default symbol. `stats.json` holds the group-by response.

```
$ cat layer.json
{"name":"zones","objectIdField":"OBJECTID","drawingInfo":{"renderer":{"type":"uniqueValue","field1":"ZONE","field2":"SUBTYPE","fieldDelimiter":",","uniqueValueInfos":[{"value":"A,<Null>","label":"Zone A","symbol":{"type":"esriSFS"}},{"value":"AE,<Null>","label":"Zone AE","symbol":{"type":"esriSFS"}},{"value":"X,","label":"Zone X","symbol":{"type":"esriSFS"}}]}}}
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

The two `cat` lines are real files. Each `symbol` is the shortest object the tool accepts, and a real layer holds a full one.

The tool reads each null in the data as the text `<Null>`, joins the values with the renderer's
delimiter, and compares the result with the class values as text. A null is not an empty string.
`X,` in the data is an empty sub-type, and it matches the class `X,`.

| Finding | Severity | What it means |
|---|---|---|
| `NULL_TOKEN` | FAIL when the class holds rows, or when rows are not counted | A class value has the token as one of its parts. This is the story. |
| `NULL_TOKEN` | LATENT | The same class, but no row is in it now. It fails the day a row arrives. The verdict says "clean now" and counts these classes. |
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
`--apply` the tool says so and writes nothing. A second `--apply` run with the same path is
refused, because the file now exists.

A text cell (`kind`, `severity`, `key`, `detail`) that starts with `=`, `+`, `-`, `@`, a tab or a
carriage return gets one apostrophe in front, so that most spreadsheets show it as text and not as a
formula ([OWASP: CSV Injection](https://community.owasp.org/attacks/CSV_Injection) lists those
triggers and the single-quote prefix). A key built from the data, such as `-5,x`, is stored as
`'-5,x`. The `rows` column stays a plain number. The tool never reads its own CSV back. A reader
that wants the original text removes exactly one leading apostrophe from a cell that began with one
of those characters. The self-test pins each trigger on each text column, and an end-to-end
`--apply` run with a `-5` key.

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
$ python rendergap.py --layer-json layer.json --stats-json stats.json --out findings.csv --apply
error: --out findings.csv already exists. Name a new file.
```

### A run on the renderer alone

`--static` reads the renderer and no data. It still fails on a class that carries the token, but it
cannot say how many rows are in it, and it cannot say which values are unmatched.

```
$ python rendergap.py --layer-json layer.json --static
...
data: not queried (--static)

classes that carry the <Null> token: (2)
  class 'A,<Null>' (label 'Zone A'): rows not counted, the data was not compared
  class 'AE,<Null>' (label 'Zone AE'): rows not counted, the data was not compared

no default symbol, so a value added later will have none: (1)
  the renderer has no default symbol. The data was not compared.
...
```

A `--static` run with no finding exits 4 and says "NOT CHECKED", because it looked at no data.

## How it asks the data

`--url` sends up to three GET requests. A cut, empty or unverified null-token response skips the third, so it sends two. The first reads the layer JSON. The second is a group-by statistics
query on the renderer's fields. The third is a `returnCountOnly` query that compares the group counts
with the layer's row count (see Limits). This is the group-by query the tool sends for the layer above:

```
<layer url>/query
  f=json
  where=1=1
  returnGeometry=false
  groupByFieldsForStatistics=ZONE,SUBTYPE
  outStatistics=[{"statisticType": "count", "onStatisticField": "OBJECTID", "outStatisticFieldName": "rendergap_n"}]
```

The statistic is a count of the layer's object-ID field, not of a renderer field. A SQL `COUNT` on
a column skips the nulls, so a count on the second renderer field would return a count of 0 for the
null class. The self-test stub counts like SQL. With the sub-type field counted, the 40 null rows
come back as 0, and the run refuses the response with exit 2. With the object-ID field, it reports
40 of 100. Esri documents the skip for the geoprocessing tool Summary Statistics, and I did not
find it stated for the REST query. The object-ID field is never null, so the question does not
arise.

A group that exists holds at least one row, so a count of 0 in a statistics response is always a
mistake. The tool refuses it. If you build `stats.json` by hand, send the query above, or one like
it, and count the object-ID field.

The tool finds the object-ID field from the layer's `objectIdField`, or else from the field whose
type is `esriFieldTypeOID`. If the layer names neither, the run exits 4.

### The token

`--token-env NAME` reads a token from the environment variable `NAME` and sends it in an
`X-Esri-Authorization: Bearer <token>` header. The token is never put in a URL. A `--url` that
carries a query string or a password is refused.

The tool strips white space from both ends of the token, because a token file read with
`$(cat token.txt)` ends in a line break. A token with a control character inside it, or with a
character outside ASCII, cannot ride in an HTTP header. The tool refuses it with exit 64 and
never prints it.

The tool sends the token only over `https`, or to a loopback address. It does not follow a redirect,
because a redirect would send the header to whatever host answers. If a server echoes the token
back in an error message, the tool replaces it with `***`, before it cuts the message to 200
characters. The message and traceback of an unexpected crash are redacted the same way. Every line the
tool prints is redacted, the path of `--out` included, and so is the findings file, because a service can echo the token into a
renderer type or a class label.

The self-test proves each of these against the stub, and greps the output, the errors and the
findings file for the token. That includes a 460 character token, which is longer than the cut.

The tool has no flag that takes a token on the command line. If you guess one, such as `--token`, and
type the secret after it, the usage error counts the unrecognized arguments and does not print them.
The self-test pins this for a flag-and-value pair and for a stray positional. A value that a known
flag refuses, such as `--sample abc` or `--static=abc`, is not printed either. The usage error names
the flag and says the text is not shown.

## Layer files

`--layer-json` also reads a `.lyrx` layer file. Pro writes `fieldValues` as a list, so a null
appears as `<Null>` in the list. The tool joins the list with a comma. The file must hold exactly
one layer with a renderer.

I made a two-field unique-value layer with `arcpy` 3.6 once and saved it as a layer file. I read
these facts from that file. I did not keep it, so you cannot reproduce them from this repository.

- The null class has `fieldValues` of `["A", "<Null>"]`, and its label is `A, <Null>`.
- An empty string is stored as `""`, so it stays apart from the null.
- The file has a `defaultSymbol` with a symbol and no `useDefaultSymbol` key. The arcpy object
  reports `useDefaultSymbol` as `False` for the same layer.

So Pro leaves out `useDefaultSymbol` while it is false. This tool draws a default symbol only when
the key is present and true. The Pro SDK says the property is "whether or not to use the default
symbol", and the arcpy page says it controls "the display of un-added values". Neither page says
what an absent key means, so this reading comes from the one file I made.

The self-test builds a synthetic layer file of the same shape and checks the tool against it. This
run uses another synthetic file, `widgets.lyrx`, with the classes `A, <Null>`, `B, x` and `C, `, no
`useDefaultSymbol` key, and five rows:

```
$ python rendergap.py --layer-json widgets.lyrx --stats-json widgets-stats.json
rendergap: widgets.lyrx
renderer: unique value on KIND, SUBKIND, 3 class value(s), default symbol none
features: 5 in 3 value combination(s)

classes that carry the <Null> token: (1)
  class 'A,<Null>' (label 'A, <Null>'): 2 of 5 features (40.0%) are in it

no default symbol, so a value added later will have none: (1)
  the renderer has no default symbol. Every value combination read has a class.

VERDICT: 1 finding(s). The features in these groups may draw no symbol or lose their pop-up in a client.
```

### The lints

A layer file can carry a `defaultSymbol` that is null, or a symbol reference with no symbol. It can
also carry a `valueExpressionInfo` with an empty expression. The tool reports each as a lint.

These are lints, not findings. They come from one investigation in which a map service worker was
suspected of crashing on such a renderer. That investigation tested a hypothesis, and I have not
reproduced it. A lint does not change the exit code. `--fail-on-lint` makes it do so.

## Documentation checked

I read these pages on 2026-10-13 and 2026-11-11, as each row says. The status column says what each page supports.

| Behaviour the tool relies on | Status | Source |
|---|---|---|
| `groupByFieldsForStatistics` and `outStatistics` are query parameters. | Documented | [Query (Feature Service/Layer)](https://developers.arcgis.com/rest/services-reference/enterprise/query-feature-service-layer/) |
| `exceededTransferLimit: false` means there are no more pages. | Documented for paged queries. The page does not say a group-by query returns the flag, so the tool treats `true` as a cut, and also a response as long as the layer's `maxRecordCount` (see Limits). | The same page |
| `returnCountOnly` returns `{"count": n}`, the number of features the query would return. | Documented, read on 2026-11-11. The page's example response is `{ "count": 48 }`. The tool sends it with `where=1=1`. | The same page |
| `returnGeometry` takes `true` or `false`. | Documented. The page's list of the "only other parameters" usable with `outStatistics` does not name it. The service I ran accepted it. | The same page |
| A unique-value renderer has `field1`, `field2`, `field3`, `fieldDelimiter`, `defaultSymbol`, `defaultLabel` and `uniqueValueInfos` with `value`. | Shown in the syntax block and an example only. The page gives no property descriptions for these fields (read on 2026-11-12). | [Renderer objects](https://developers.arcgis.com/rest/services-reference/enterprise/renderer-objects/) |
| A `defaultSymbol` of `null` assigns no symbol to an unmatched feature. | Documented. The page's known limitation, that a generic symbol may show anyway, is tied to SceneLayers with a mesh geometry type only. | [UniqueValueRenderer](https://developers.arcgis.com/javascript/latest/references/core/renderers/UniqueValueRenderer/) |
| The default delimiter is a comma when two fields are set. | Documented (JavaScript SDK) | The same page |
| A layer has `objectIdField` and fields of type `esriFieldTypeOID`. | Documented | [Feature layer](https://developers.arcgis.com/rest/services-reference/enterprise/layer-feature-service/) |
| Send a token in `X-Esri-Authorization` with the `Bearer` scheme (the documented header form). | Documented | [Accessing ArcGIS token-secured web services](https://enterprise.arcgis.com/en/server/11.1/administer/linux/accessing-arcgis-token-secured-web-services.htm) |
| `useDefaultSymbol` controls whether unmatched values are displayed. | Documented in one line | [arcpy.mp UniqueValueRenderer](https://doc.esri.com/en/arcgis-pro/latest/arcpy/mapping/uniquevaluerenderer-class.html), [CIMUniqueValueRenderer.UseDefaultSymbol](https://doc.esri.com/en/arcgis-pro/3.7/sdk/api-reference/topic6161.html) |
| `COUNT` skips nulls. | Documented for the Summary Statistics tool only. The Query page does not state it. | [Summary Statistics](https://desktop.arcgis.com/en/arcmap/10.5/tools/analysis-toolbox/summary-statistics.htm) |
| A browser client does not match a class value that contains `<Null>`. | Not documented. The renderer reference and the JavaScript reference do not mention the token. | Observed in one deployment |
| A service answers a bad request with a JSON `error` body and HTTP 200. | Not documented on the page I read | The tool treats an error body and an HTTP error status alike |
| A missing key means `useDefaultSymbol` is false in a layer file. | Not documented | One file made with `arcpy` 3.6 |

I tried to reproduce the browser behaviour with the ArcGIS Maps SDK for JavaScript in a headless
browser. The SDK did not load in that setup, so the claim in the story is unreproduced here. The
tool does not depend on it: it reports the class and the row count, and you decide.

## Run against a public service

The National Flood Hazard Layer is a public map service. Its flood-zone layer uses unique values on
`FLD_ZONE` and `ZONE_SUBTY` with the delimiter `;`, and it has classes such as `AE;<Null>`.

This excerpt leaves out every line that carries a row count. Each `...` marks lines left out.

```
$ python rendergap.py --url https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28
rendergap: https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28
renderer: unique value on FLD_ZONE, ZONE_SUBTY, 106 class value(s), default symbol none
...
classes that carry the <Null> token: (9)
...
  class 'AR;<Null>' (label '1% Annual Chance Flood Hazard'): no feature is in it now
...
value combinations with no class and no default symbol: (16)
...
VERDICT: 24 finding(s). The features in these groups may draw no symbol or lose their pop-up in a client.
```

On 2026-10-13 the layer held about 5.8 million features in 69 value combinations (a re-run on 2026-11-12 counted 68). The 9 classes that carry the
token hold about a fifth of them between them, and one of the 9 holds none. The largest
group with no class, `X;AREA OF MINIMAL FLOOD HAZARD`, holds about one feature in seven. The exit
code was 1.

The run took a few seconds on 2026-10-13. One earlier attempt on the same day ended with a
connection reset, so the tool exited 2. I did not add a retry. The timings and the class and row counts are dated
observations, not claims that the self-test checks. The public service has since changed: it reported 128 classes on 2026-11-11.

This shows that the tool runs end to end against a real service. It does not show that any client
drops these features. I tested no client against this layer, and the layer is not the one in the
story. The `X;AREA OF MINIMAL FLOOD HAZARD` group may be undrawn on purpose.

## Limits

- It reads a unique-value renderer only. A simple or class-breaks renderer exits 4. A renderer with a non-empty Arcade `valueExpression` (REST) or `valueExpressionInfo` (`.lyrx`) exits 4, even when it also names fields.
- A renderer with no `uniqueValueInfos` entries exits 4, and that includes one that stores its classes only in `uniqueValueGroups`. The tool reads `uniqueValueInfos`.
- A layer file with more than one renderer exits 4. Save one layer at a time.
- The comparison is exact text. Case and surrounding spaces count. A date field or a coded-value
  domain may show the value in a different form in the renderer than in the group-by response, and
  then every row would look unmatched. Check the first run by eye.
- A class written with a decimal point (`5.0`, `5.50`, up to 15 characters) is compared in the same plain form (`5`, `5.5`), so it meets a data value `5` or `5.5`. A numeric value `5.0` in the data already reads as `5`. Only the class is normalised, so a text value `5.0` in the data does not meet a class `5` and shows as a gap. The comparison does not know the field type, so a text field that holds `5` still meets a class `5.0`, and a text class `5.0` meets a data value `5`. Other number formats are not normalised.
- Floating-point class values compare as text, so a data value of `0.30000000000000004` does not match the class `0.3` and shows as a gap.
- The query uses `where=1=1` and sets no time or geometry filter. I did not test what a layer
  definition expression does to it.
- A response cut at the server's record limit exits 4 when no class carries the token. The tool does not page through grouped
  results. A layer with more value combinations than the limit needs a higher `maxRecordCount`.
- The Query page does not say that a group-by response carries `exceededTransferLimit`. The tool therefore also treats a response with as many rows as the layer's `maxRecordCount` as cut and exits 4. A layer whose answer has exactly that many value combinations also exits 4, and a higher `maxRecordCount` clears it. A layer file without `maxRecordCount` gets only the flag check, with one exception: a null-token class that has no rows in the response is then not trusted as latent, because a cut that the server did not flag would look the same. That run reads "cannot be ruled out", does not count the rows, and exits 1. Under `--url` the tool also asks for the layer's own row count (`returnCountOnly`) and compares it with the sum of the group counts. A response that is cut without a flag, or that leaves a group out, then exits 4 with both numbers, or 1 when a class carries the token. A layer file and a statistics file carry no total, so a silent cut in saved files is not caught.
- A layer with no rows exits 4 only when no class carries the token. Otherwise the null-token class fails the run with exit 1.
- A group-by over a very large layer can be slow or refused by the service. The public layer above
  has about six million rows and answered in a few seconds. Your service may differ.
- There is no retry. A connection reset exits 2.
- The group-by response has to name each renderer field exactly as the renderer does.
- A server that upper-cases the statistics column name (`RENDERGAP_N`) makes the run exit 2 with "has no rendergap_n". The name match is case sensitive.
- `NULL_TOKEN` is a risk, not a measured loss. The evidence is one deployment and one browser client.
- A single-field renderer with a `<Null>` class is flagged the same way, but the browser behaviour was observed only for two fields.
- Two classes with the same value give two `NULL_TOKEN` findings, which inflates the finding count.
- A layer that leaves some values undrawn on purpose, such as the `X;AREA OF MINIMAL FLOOD HAZARD` group above, exits 1. The tool cannot tell a deliberate gap from a mistake.
- A text-field class `5.0` is treated as meeting data value `5`, because the comparison ignores the JSON type that the statistics response carries. A layer whose text codes hold both `5` and `5.0` can exit 0 when one of them has no class.
- A null-token class on a layer with zero features exits 1 and prints "The features in these groups may draw no symbol", which is wrong for a layer with no features. The exit 1 is the conservative direction.
- Console output shows a carriage return or tab in a data key unchanged, so a key of CR then `x,q` prints as `x,q`. Only the CSV is guarded.
- A service value that holds a lone surrogate, such as JSON `\ud800`, cannot be encoded as UTF-8, so `--apply` exits 2 with "could not write" and leaves no partial file.
- A token of one or two characters is redacted wherever its text occurs, so the console output of such a run is hard to read. No token leaks.
- `--static` finds null-token classes and a missing default symbol, but not the values that are actually unmatched.
- A `--static` run never exits 0. A run that finds no defect exits 4, so a job cannot read it as a compared clean run.
- A layer file saved by Windows PowerShell 5 redirection is UTF-16, and the tool reports it as "is not JSON" (exit 2), which hides the real cause.
- The "Layer files" section quotes facts from a file made with `arcpy` 3.6 and a run on five rows. The repo holds no such file, so you cannot reproduce them.
- A `--url` that ends in `?` passes the URL check and sends `??f=json`, which most servers answer with a page that is not JSON (exit 2).
- A `--url` with a space, a control character, a non-ASCII character (write a host name in punycode), a bad port or an unclosed IPv6 bracket exits 64 before any request. The self-test pins each of these cases.
- A server that does not speak HTTP, such as a TLS alert on a plain http port, exits 2 as "could not reach". The self-test pins a reply that is not HTTP at all.
- If `HTTP_PROXY` is set, a token sent to a loopback http address goes to the proxy in clear text, because the tool does not bypass the proxy for loopback. The self-test sets `NO_PROXY` for itself.
- The loopback test reads the host name only, so a name such as `localhost` that a hosts file points elsewhere still receives the token over plain http.
- The redaction replaces the exact token text only. A server that echoes the token URL-encoded, in another case or cut short is not redacted.
- Only a CSV cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return is guarded. The guard does not guard a line feed, and it does not look past a leading space, so a cell such as ` =x` is not guarded and I did not verify how Excel treats it. The guard adds an apostrophe and never strips one, and the apostrophe stays visible in a viewer that does not treat it as a text marker.
- A layer response with no `drawingInfo`, such as a Table, exits 4 with a message that says the renderer type is not `uniqueValue`, which reads as if a renderer exists.
- A run that exits 4 writes no `--out` file even under `--apply`, because a CSV with no findings would read as a clean run. The tool prints "NOT CHECKED, so X was not written". A job that expects the CSV must check for exit 4 first.
- An unrecognized argument, such as a guessed `--token` followed by a secret, is counted in the usage error and never echoed. A refused value of a known flag (`--sample abc`, `--static=abc`) is also not echoed: the usage error names the flag and says the text is not shown.
- `--out` without `--apply` is a dry run and writes nothing, although the flag table says "Needs `--apply`".
- The tool never reads its own CSV, so a reader strips one leading apostrophe itself. The self-test pins that strip on its own read-back.
- A reply cut off in the middle of the JSON exits 2. A reply with a content length that falls short reads as "is not JSON", and a chunked reply that stops mid-chunk reads as "could not reach", so a dropped connection can read as bad JSON.
- A `.lyrx` unique-value renderer whose groups, classes or values are not lists of objects, whose `fieldValues` is not a list, or that holds no class, exits 4 with a message. The REST path refuses a renderer with zero classes the same way. A shape that Pro writes in another form is refused, not guessed.
- The Esri page shows the `X-Esri-Authorization` header form for a token. It does not say that a query parameter is wrong; the tool uses the documented header form.
- A failed `--out` write exits 2 even when findings (exit 1) exist, so read the printed verdict.
- The self-test writes one temporary directory and removes it. That is the only write besides `--out`.
- A dry run prints "Check only. X was not written" without checking that the folder of X is writable, so the failure appears only on the `--apply` run.
- The self-test opens dozens of loopback connections. On a machine that has run out of ephemeral ports (Windows error 10048) its wire assertions fail with "could not reach", and a re-run after the sockets drain passes.
- Under `--url` the count check is a second query, not one snapshot. A layer that is edited between the two queries exits 4 with a count mismatch, and a re-run clears it. A service that answers `returnCountOnly` with a different `where` meaning than the group-by is not detected.
- An empty layer that has a null-token class exits 1 and prints "rows not counted" and "the data was not compared". The tool stops at "the layer has no rows" and reports no compared groups.
- A server-supplied string, such as a renderer type or a class label, is redacted for the exact token text only (the self-test pins the renderer type, the class label and the CSV). It prints to the console and goes to the CSV otherwise unfiltered, so a hostile service can send a value with a line feed that forges a second "VERDICT" line, or terminal escape sequences.
- OWASP says its listed sanitisation techniques, taken as a group, are not reliable, and I did not test the apostrophe prefix in Excel after a save and reopen. OWASP also lists line feed and full-width `=` `+` `-` `@` as triggers, which this tool does not guard.
- A leading apostrophe in the CSV may be the guard or the original text, so stripping it is lossy for data that began with an apostrophe.
- The CSV is UTF-8 with no byte order mark. Import it as UTF-8 in Excel, because a double click may show non-ASCII keys as garbled text.
- The dated observations (the NFHL run on 2026-10-13, the `gh search repos rendergap` result, the 128 classes on 2026-11-11) are not exercised by the self-test and were not re-run. They stay honest only because they carry their dates.
- The `kind` and `severity` CSV cells are fixed constants, so their guard is defensive only. The CSV detail guard is defensive too. A real detail cell starts with `class '`, the quoted key or fixed text, so only the key column can carry a hostile leading character.
- A `--url` reply that starts with a UTF-8 byte order mark exits 2 as "is not JSON". A file with one is read.
- Ctrl-C is not caught: `main()` catches `Exception`, not `KeyboardInterrupt`, so an interrupted run ends with a Python traceback and the interpreter's interrupt status, not one of the documented exit codes.
- `TIMEOUT_SECONDS` bounds each socket read, not the whole request, so a server that drips bytes can keep a run alive past 60 seconds.
- A deeply nested JSON document raises `RecursionError`, which exits 70 (tool fault) and not 2.
- Microsoft's Winsock error page describes 10048 (`WSAEADDRINUSE`) as "Address already in use" and says a client's `connect` chooses an unused port automatically (https://learn.microsoft.com/en-us/windows/win32/winsock/windows-sockets-error-codes-2). It does not say that running out of ephemeral ports gives 10048, so that cause rests on my own runs. The Python `urllib.request` page says `ProxyHandler` reads `<protocol>_proxy` variables and that `no_proxy` lists the hosts to reach without a proxy (https://docs.python.org/3.12/library/urllib.request.html). It does not mention loopback or an upper-case `NO_PROXY`, so the loopback claim rests on my own runs.
- The rows of the "Documentation checked" table on renderer objects and `objectIdField` say "Documented" where the page lists the fields without describing them.
- A `--url` that ends in `#` passes the URL check. The fragment swallows the query on the wire, so the server gets no `f=json` and most answer with a page that is not JSON (exit 2).
- A label that holds non-ASCII text prints in the console code page. A log made by redirecting the output may show it garbled (cp1252 on Windows). The run does not crash, and the CSV is UTF-8 and correct.
- The `layer.json`, `stats.json` and `widgets.lyrx` files in the examples are not in the repo. The `layer.json` and `stats.json` outputs reproduce from the text shown. The `widgets.lyrx` output cannot be reproduced from the repo.
- A failed `--self-test` exits 1, the same code as "findings exist". Do not schedule it beside a findings gate.
- An empty `--token-env ""`, for example from an unset shell variable in `--token-env "$NAME"`, counts as no `--token-env` flag. The run then queries the service with no token, while a named variable that is unset or empty exits 64.
- A consumer that closes the pipe before the report is printed, such as `| head -1` on a long report, makes the run exit 70 (tool fault), not a verdict.
- The redaction covers only the token from `--token-env`. A secret that you put in the `--url` path or in another argument is printed in the source line and in error messages.
- A REST renderer with a blank `valueExpression` (empty or spaces only) is compared on its fields. A non-empty `valueExpression` exits 4, because the Esri JavaScript `UniqueValueRenderer` page calls it an alternative to `field`, and the tool cannot query an expression.
- A null-token class that holds no feature reads as latent. The run exits 0 only when the layer file names a `maxRecordCount` and has a default symbol; without `maxRecordCount` the same input exits 1 with "rows not counted" (see the record-limit line above). The exit 0 holds when the data has a near match, such as `A,<Null>` for a class `a,<Null>` (the comparison is case sensitive): the default symbol draws those features. Without a default symbol the same data exits 1.
- A class value or a data value that contains the delimiter can merge two groups. For example `('A,B','')` and `('A','B,')` both read as `A,B,`. It takes commas inside classification values.
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

- [svcdrift](https://github.com/uhsear/svcdrift) - diffs a service against its source dataset or another service, renderer classes included. Its `--probe` reads one row and never counts the rows in a class
- [cimscan](https://github.com/uhsear/cimscan) - lists the data sources in project and layer files
- [idreuse](https://github.com/uhsear/idreuse) - the same habit for a join: refuse the match the geometry disproves
- [restfake](https://github.com/uhsear/restfake) - a mock ArcGIS REST server that injects faults such as an error body under HTTP 200. The stub in this tool's self-test is smaller.
