#!/usr/bin/env python
"""Flag the unique-value classes and missing default symbols that make features vanish from a map.

Reads a layer's unique-value renderer, asks the data which value combinations
really occur, and reports three things a renderer-only check cannot see: a class
whose value carries the <Null> token, a value combination that no class covers
while no default symbol exists, and a default symbol that is empty.

A layer symbolised on two fields stores the class for a row with a null in the
second field as "A,<Null>". In the case that prompted this tool, the server drew
that row and a browser client did not, so the row lost its symbol and its
pop-up. Esri's renderer reference does not mention the token, so this is an
observed behaviour. A diff of the data's values against the renderer's classes
reports such a layer as clean, because the class is there and the value is
there. Only a count of the rows in a null-token class shows how many features
are at risk.

The obvious tool stops short of that. ArcGIS Pro's arcpy.mp can list the values
missing from a unique-value renderer. It runs inside Pro's Python, and its
documentation describes a list of values, not a count of rows or a check for
the <Null> token. This tool needs no Pro. It reads the layer's REST endpoint,
or two saved JSON files, and counts the rows with a group-by statistics query.

    python rendergap.py --self-test
    python rendergap.py --url https://host/arcgis/rest/services/S/MapServer/0
    python rendergap.py --url https://host/.../FeatureServer/0 --token-env GIS_TOKEN
    python rendergap.py --layer-json layer.json --stats-json stats.json
    python rendergap.py --layer-json layer.lyrx --static
    python rendergap.py --url ... --out findings.csv --apply

Nothing is written without --apply, and the only file it writes is --out.
The tool sends GET requests and never changes a service.

Exit codes: 0 compared and nothing flagged, 1 at least one feature loss was
flagged, 2 a source could not be read or the output could not be written,
4 nothing was compared (an unsupported renderer, a response cut at the
server's limit, or a layer with no rows), 64 usage error, 70 an unexpected
crash, which is never a finding.
"""

from __future__ import print_function

import argparse
import contextlib
import csv
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
import urllib.error
import urllib.parse
import unittest.mock
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

# =============================================================================
# CONFIGURATION. Deliberately not flags. Change here, not at the call site.
# =============================================================================

# The text a null takes inside a class value and inside a legend label. Pro
# writes it into fieldValues when it builds a class from a null. The tool
# writes the same text for a null it reads from the data, so the two compare.
NULL_TOKEN = "<Null>"

# The name of the count column in the group-by query. A saved response given to
# --stats-json must use this name.
COUNT_FIELD = "rendergap_n"

# The separator for a renderer that names none, and for a layer file, whose
# classes keep their values as a list. Esri's JavaScript reference says a comma
# is the default when two fields are set.
DEFAULT_DELIMITER = ","

# How many findings are listed under each heading.
DEFAULT_SAMPLE = 10

# Hosts a token may be sent to over plain http.
LOOPBACK = ("127.0.0.1", "localhost", "::1")

# One request must finish within this many seconds.
TIMEOUT_SECONDS = 60

# A response over this many bytes is refused instead of read into memory.
MAX_BYTES = 20 * 1000 * 1000

# =============================================================================
# End of CONFIGURATION.
# =============================================================================

# Finding kinds, in the order they print.
NULL_CLASS = "NULL_TOKEN"
HIDDEN = "HIDDEN"
NO_DEFAULT = "NO_DEFAULT"
DEFAULTED = "DEFAULTED"
LINT_DEFAULT = "LINT_DEFAULT"
LINT_EXPRESSION = "LINT_EXPRESSION"

# Severities. FAIL sets exit 1. LATENT, INFO and LINT never do, except that
# --fail-on-lint raises LINT to a failure.
FAIL = "FAIL"
LATENT = "LATENT"
INFO = "INFO"
LINT = "LINT"

HEADINGS = (
    (NULL_CLASS, "classes that carry the %s token:" % NULL_TOKEN),
    (HIDDEN, "value combinations with no class and no default symbol:"),
    (NO_DEFAULT, "no default symbol, so a value added later will have none:"),
    (DEFAULTED, "value combinations drawn by the default symbol:"),
    (LINT_DEFAULT, "lint, an empty default symbol (a hypothesis, see README):"),
    (LINT_EXPRESSION, "lint, an empty value expression (a hypothesis, see README):"),
)

OUT_COLUMNS = ("kind", "severity", "key", "rows", "detail")


class Unsupported(Exception):
    """The renderer or the response cannot be compared. Exit 4, never a pass."""


class SourceError(Exception):
    """A source could not be read, or answered with an error. Exit 2."""


class Renderer(object):
    """The part of a unique-value renderer the check reads."""

    def __init__(self, fields, delimiter, classes, has_default, lints=()):
        self.fields = fields
        self.delimiter = delimiter
        self.classes = classes          # [(class value, label)]
        self.has_default = has_default
        self.lints = lints              # [(kind, text)]


class Finding(object):
    def __init__(self, kind, severity, key, rows, text):
        self.kind = kind
        self.severity = severity
        self.key = key
        self.rows = rows
        self.text = text


class Report(object):
    def __init__(self, renderer, groups, total, findings, incomplete, static):
        self.renderer = renderer
        self.groups = groups            # {value combination: rows} or None
        self.total = total
        self.findings = findings
        self.incomplete = incomplete    # why the data was not compared, or None
        self.static = static


# ------------------------------------------------------------ the pure core

def text_of(value):
    """The text a value takes in a class key. A null is the token."""
    if value is None:
        return NULL_TOKEN
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return "%d" % value
    return str(value)


def group_key(values, delimiter):
    return delimiter.join(text_of(v) for v in values)


def has_null_token(key, delimiter):
    """True when the token is a whole part of the key, not a piece of a word."""
    token = NULL_TOKEN
    return (key == token or key.startswith(token + delimiter)
            or key.endswith(delimiter + token)
            or (delimiter + token + delimiter) in key)


def _items(value):
    return [i for i in value if isinstance(i, dict)] if isinstance(value, list) \
        else []


def from_rest(r):
    """A renderer from the REST drawingInfo form."""
    if r.get("type") != "uniqueValue":
        raise Unsupported("the renderer type is %s, not uniqueValue, so there "
                          "are no classes to compare" % text_of(r.get("type")))
    fields = [r[k] for k in ("field1", "field2", "field3")
              if isinstance(r.get(k), str) and r[k]]
    if not fields:
        raise Unsupported("the renderer names no field, so its classes come "
                          "from an expression this tool cannot query")
    infos = r.get("uniqueValueInfos")
    if not isinstance(infos, list):
        raise Unsupported("the renderer has no uniqueValueInfos list "
                          "(uniqueValueGroups is not read)")
    classes = []
    for index, info in enumerate(infos):
        if not isinstance(info, dict) or "value" not in info:
            raise Unsupported("uniqueValueInfos entry %d has no value" % index)
        classes.append((text_of(info["value"]), str(info.get("label") or "")))
    delimiter = r.get("fieldDelimiter")
    if not isinstance(delimiter, str) or not delimiter:
        delimiter = DEFAULT_DELIMITER
    symbol = r.get("defaultSymbol")
    return Renderer(fields, delimiter, classes,
                    isinstance(symbol, dict) and bool(symbol))


def from_cim(r):
    """A renderer from the CIM form a layer file stores."""
    if r.get("type") != "CIMUniqueValueRenderer":
        raise Unsupported("the renderer type is %s, not CIMUniqueValueRenderer, "
                          "so there are no classes to compare"
                          % text_of(r.get("type")))
    fields = r.get("fields")
    if not isinstance(fields, list) or not fields or \
            not all(isinstance(f, str) and f for f in fields):
        raise Unsupported("the renderer names no field, so its classes come "
                          "from an expression this tool cannot query")
    lints = []
    info = r.get("valueExpressionInfo")
    if isinstance(info, dict):
        if str(info.get("expression") or "").strip():
            raise Unsupported("the renderer classifies on an Arcade "
                              "expression, which this tool cannot query")
        lints.append((LINT_EXPRESSION,
                      "valueExpressionInfo is present with an empty expression"))
    classes = []
    for group in _items(r.get("groups")):
        for cls in _items(group.get("classes")):
            for value in _items(cls.get("values")):
                parts = value.get("fieldValues")
                if isinstance(parts, list):
                    classes.append((group_key(parts, DEFAULT_DELIMITER),
                                    str(cls.get("label") or "")))
    reference = r.get("defaultSymbol")
    drawn = isinstance(reference, dict) and bool(reference.get("symbol"))
    if not drawn:
        lints.append((LINT_DEFAULT,
                      "defaultSymbol is null or a symbol reference with no "
                      "symbol"))
    # Pro leaves useDefaultSymbol out of the file while it is false, so only an
    # explicit true means the default symbol draws.
    return Renderer(fields, DEFAULT_DELIMITER, classes,
                    drawn and r.get("useDefaultSymbol") is True, lints)


def extract_renderer(doc):
    """(renderer, object id field name) from a layer's JSON, a layer file or a
    bare renderer."""
    oid = None
    if "layerDefinitions" in doc:
        layers = [d for d in _items(doc["layerDefinitions"])
                  if isinstance(d.get("renderer"), dict)]
        if len(layers) != 1:
            raise Unsupported("the layer file holds %d layers with a renderer; "
                              "this tool reads exactly one" % len(layers))
        raw = layers[0]["renderer"]
    elif "drawingInfo" in doc:
        info = doc["drawingInfo"]
        raw = info.get("renderer") if isinstance(info, dict) else None
        if not isinstance(raw, dict):
            raise Unsupported("the layer has a drawingInfo with no renderer")
        oid = doc.get("objectIdField")
        for field in _items(doc.get("fields")):
            if not oid and field.get("type") == "esriFieldTypeOID":
                oid = field.get("name")
    elif "type" in doc:
        raw = doc
    else:
        raise Unsupported("this JSON is not a layer, a layer file or a "
                          "renderer. A service root has no renderer; name a "
                          "layer URL that ends in a number")
    cim = str(raw.get("type")).startswith("CIM")
    return (from_cim(raw) if cim else from_rest(raw)), \
        (oid if isinstance(oid, str) and oid else None)


def stats_params(fields, oid):
    """The group-by query. The count is on the object id field because a count
    on a nullable field does not count the nulls."""
    return {
        "f": "json",
        "where": "1=1",
        "returnGeometry": "false",
        "groupByFieldsForStatistics": ",".join(fields),
        "outStatistics": json.dumps([{
            "statisticType": "count", "onStatisticField": oid,
            "outStatisticFieldName": COUNT_FIELD}]),
    }


def _count(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or value < 0 or (isinstance(value, float)
                             and not value.is_integer()):
        raise SourceError("a count in the statistics response is %r, not a "
                          "whole number" % (value,))
    return int(value)


def parse_stats(doc, renderer):
    """({value combination: rows}, cut at the server's limit) from a response."""
    features = doc.get("features")
    if not isinstance(features, list):
        raise SourceError("the statistics response has no features list")
    groups = {}
    for index, feature in enumerate(features):
        attrs = feature.get("attributes") if isinstance(feature, dict) else None
        missing = [f for f in renderer.fields + [COUNT_FIELD]
                   if not isinstance(attrs, dict) or f not in attrs]
        if missing:
            raise SourceError("statistics row %d has no %s" %
                              (index, ", ".join(missing)))
        key = group_key([attrs[f] for f in renderer.fields],
                        renderer.delimiter)
        groups[key] = groups.get(key, 0) + _count(attrs[COUNT_FIELD])
    return groups, doc.get("exceededTransferLimit") is True


def _quote(key):
    return "'%s'" % key


def analyze(renderer, groups, incomplete=None, static=False):
    """The findings. groups is None when the data was not compared."""
    findings = []
    total = None if groups is None else sum(groups.values())
    labels = {}
    for key, label in renderer.classes:
        labels.setdefault(key, label)
    for key, label in renderer.classes:
        if not has_null_token(key, renderer.delimiter):
            continue
        rows = None if groups is None else groups.get(key, 0)
        if rows is None:
            where = "rows not counted, the data was not compared"
        elif rows == 0:
            where = "no feature is in it now"
        else:
            where = ("%d of %d features (%.1f%%) are in it"
                     % (rows, total, 100.0 * rows / total))
        findings.append(Finding(
            NULL_CLASS, LATENT if rows == 0 else FAIL, key, rows,
            "class %s%s: %s" % (_quote(key),
                                " (label %s)" % _quote(label) if label else "",
                                where)))
    hidden = False
    if groups is not None:
        for key in sorted(groups, key=lambda k: (-groups[k], k)):
            if key in labels:
                continue
            if renderer.has_default:
                findings.append(Finding(
                    DEFAULTED, INFO, key, groups[key],
                    "%s: %d feature(s), drawn by the default symbol"
                    % (_quote(key), groups[key])))
            else:
                hidden = True
                findings.append(Finding(
                    HIDDEN, FAIL, key, groups[key],
                    "%s: %d feature(s) match no class and have no default "
                    "symbol" % (_quote(key), groups[key])))
    if not renderer.has_default and not hidden:
        findings.append(Finding(
            NO_DEFAULT, LATENT, "", None,
            "the renderer has no default symbol. %s" %
            ("The data was not compared." if groups is None else
             "Every value combination read has a class.")))
    for kind, text in renderer.lints:
        findings.append(Finding(kind, LINT, "", None, text))
    return Report(renderer, groups, total, findings, incomplete, static)


def gate(report, fail_on_lint=False):
    """The exit code a scheduled job reads."""
    if any(f.severity == FAIL or (f.severity == LINT and fail_on_lint)
           for f in report.findings):
        return 1
    return 4 if report.incomplete else 0


def _section(out, heading, lines, sample):
    out.append("")
    out.append("%s (%d)" % (heading, len(lines)))
    for line in lines[:sample]:
        out.append("  " + line)
    if len(lines) > sample:
        out.append("  ... %d more not listed" % (len(lines) - sample))


def describe(report, sample=DEFAULT_SAMPLE, fail_on_lint=False):
    r = report.renderer
    out = ["renderer: unique value on %s, %d class value(s), default symbol %s"
           % (", ".join(r.fields), len(r.classes),
              "present" if r.has_default else "none")]
    if report.groups is not None:
        out.append("features: %d in %d value combination(s)"
                   % (report.total, len(report.groups)))
    elif report.static:
        out.append("data: not queried (--static)")
    else:
        out.append("data: not compared. %s" % report.incomplete)
    for kind, heading in HEADINGS:
        lines = [f.text for f in report.findings if f.kind == kind]
        if lines:
            _section(out, heading, lines, sample)
    code = gate(report, fail_on_lint)
    out.append("")
    if code == 1:
        out.append("VERDICT: %d finding(s). The features in these groups may "
                   "draw no symbol or lose their pop-up in a client."
                   % sum(1 for f in report.findings if f.severity == FAIL or
                         (f.severity == LINT and fail_on_lint)))
    elif code == 4:
        out.append("VERDICT: NOT CHECKED. The data was not compared, so this "
                   "is not a clean result.")
    elif report.static:
        out.append("VERDICT: no renderer defect found. This was a static "
                   "check: the data was not queried.")
    else:
        out.append("VERDICT: clean. Every value combination has a class or a "
                   "default symbol, and no class carries the %s token."
                   % NULL_TOKEN)
    return out


# ----------------------------------------------------------------------- io

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would send the token header to whatever host answers."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def url_problem(url):
    """Why a --url is refused, or None. The token never rides in the URL."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return "--url must be an http or https address"
    if "@" in parts.netloc:
        return "--url must not carry a user name or password"
    if parts.query or parts.fragment:
        return ("--url must not carry a query string or fragment. Pass a "
                "token with --token-env.")
    return None


def _redact(text, token):
    return text.replace(token, "***") if token else text


def check_error(doc, token=None):
    error = doc.get("error")
    if error is not None:
        detail = error if isinstance(error, dict) else {"message": error}
        raise SourceError(_redact("the service returned an error: code %s, %s"
                                  % (detail.get("code"),
                                     str(detail.get("message"))[:200]), token))


def get_json(url, params, token=None):
    """One GET. The token goes in a header, redirects are refused, and a JSON
    error body counts as a failure whatever the HTTP status."""
    request = urllib.request.Request(url + "?" + urllib.parse.urlencode(params))
    if token:
        request.add_header("X-Esri-Authorization", "Bearer " + token)
    try:
        with urllib.request.build_opener(_NoRedirect).open(
                request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise SourceError("HTTP %d from %s" % (exc.code, url))
    except (urllib.error.URLError, OSError) as exc:
        raise SourceError(_redact("could not reach %s: %s" % (url, exc), token))
    if len(body) > MAX_BYTES:
        raise SourceError("the response from %s is over %d bytes" %
                          (url, MAX_BYTES))
    try:
        doc = json.loads(body.decode("utf-8"))
    except ValueError:
        raise SourceError("the response from %s is not JSON" % url)
    if not isinstance(doc, dict):
        raise SourceError("the response from %s is not a JSON object" % url)
    check_error(doc, token)
    return doc


def read_json(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        try:
            doc = json.load(handle)
        except ValueError:
            raise SourceError("%s is not JSON" % path)
    if not isinstance(doc, dict):
        raise SourceError("%s is not a JSON object" % path)
    check_error(doc)
    return doc


def write_findings(path, report):
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(OUT_COLUMNS)
        for f in report.findings:
            writer.writerow([f.kind, f.severity, f.key,
                             "" if f.rows is None else f.rows, f.text])


# ----------------------------------------------------------------- self-test

def self_test():
    """Run the assertions in a temp directory that is removed even when one
    of them raises, so a crash never leaves rendergap-selftest-* behind."""
    tmp = tempfile.mkdtemp(prefix="rendergap-selftest-")
    try:
        return _self_test(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _self_test(tmp):
    """Assertions over the decision core and the network path. The network
    path talks to a stub on 127.0.0.1 only. The only files are under tmp."""
    passed = [0]
    failed = []

    def check(cond, label):
        if cond:
            passed[0] += 1
            print("PASS  %s" % label)
        else:
            failed.append(label)
            print("FAIL  %s" % label)

    def raises(exc_type, fn, label):
        try:
            fn()
        except exc_type:
            check(True, label)
        except Exception as exc:
            check(False, "%s (wrong exception %r)" % (label, exc))
        else:
            check(False, "%s (no error raised)" % label)

    def tmpfile(name, text):
        path = os.path.join(tmp, name)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        return path

    def run_cli(argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    # ---- synthetic fixtures. Nothing here is a real layer.
    sym = {"type": "esriSFS", "style": "esriSFSSolid", "color": [1, 2, 3, 255]}

    def rest(values, fields=("KIND", "SUBKIND"), default=True, delim=","):
        out = {"type": "uniqueValue", "uniqueValueInfos": [
            {"value": v, "label": "L" + v, "symbol": sym} for v in values]}
        for index, name in enumerate(fields):
            out["field%d" % (index + 1)] = name
        if len(fields) > 1:
            out["fieldDelimiter"] = delim
        if default:
            out["defaultSymbol"] = sym
        return out

    def layer(renderer, oid="OBJECTID"):
        doc = {"name": "widgets", "drawingInfo": {"renderer": renderer},
               "objectIdField": oid, "fields": [
                   {"name": "OBJECTID", "type": "esriFieldTypeOID"}]}
        return doc

    def cim(values, default=True, use=True, expression=None,
            fields=("KIND", "SUBKIND")):
        out = {"type": "CIMUniqueValueRenderer", "fields": list(fields),
               "groups": [{"type": "CIMUniqueValueGroup", "classes": [
                   {"type": "CIMUniqueValueClass", "label": ", ".join(v),
                    "values": [{"type": "CIMUniqueValue",
                                "fieldValues": list(v)}]}
                   for v in values]}]}
        if default:
            out["defaultSymbol"] = {"type": "CIMSymbolReference",
                                    "symbol": {"type": "CIMPointSymbol"}}
        if use:
            out["useDefaultSymbol"] = True
        if expression is not None:
            out["valueExpressionInfo"] = {"expression": expression}
        return out

    def kinds(report):
        return sorted(f.kind for f in report.findings)

    print("rendergap self-test: temporary files and 127.0.0.1 only, no "
          "credentials")
    print("-" * 68)

    # ---- the token test, the thing a plain diff cannot see
    check(has_null_token("A,<Null>", ","), "'A,<Null>' carries the token")
    check(has_null_token("<Null>", ","), "a lone '<Null>' carries the token")
    check(has_null_token("<Null>,x", ","), "a leading token is found")
    check(has_null_token("a,<Null>,b", ","), "a middle token is found")
    check(not has_null_token("a,<Null>x", ","),
          "'<Null>x' is a word, not the token")
    check(not has_null_token("A,x", ","), "a key without the token is clean")
    check(has_null_token("A | <Null>", " | "),
          "the token is found with a delimiter of more than one character")

    # ---- value text, so the data and the classes compare as text
    check(text_of(None) == NULL_TOKEN, "a null reads as the token")
    check(text_of(5.0) == "5" and text_of(5) == "5",
          "5 and 5.0 are the same class value")
    check(text_of(1.5) == "1.5", "a fraction keeps its digits")
    check(text_of(True) == "true" and text_of(False) == "false",
          "a boolean reads as true or false")
    check(text_of("") == "", "an empty string stays empty, it is not a null")
    check(group_key(["A", None], ",") == "A,<Null>",
          "a null in the second field reads as 'A,<Null>'")

    # ---- the core on the disaster layer
    sfha = rest(["A,<Null>", "AE,<Null>", "X,"], default=True)
    renderer = from_rest(sfha)
    groups = {"A,<Null>": 40, "AE,<Null>": 0, "X,": 55, "B,y": 5}
    report = analyze(renderer, groups)
    by_kind = dict((f.kind, f) for f in report.findings)
    check(kinds(report) == [DEFAULTED, NULL_CLASS, NULL_CLASS],
          "the null-token classes and the defaulted group are reported")
    check(gate(report) == 1,
          "a null-token class holding rows fails the run  <-- pinned defect")
    covered = {"A,<Null>": 40, "AE,<Null>": 25, "X,": 30}
    check(not [k for k in covered if k not in dict(renderer.classes)]
          and gate(analyze(renderer, covered)) == 1,
          "a plain unmatched-values diff finds nothing wrong where every "
          "value has a class, and the run still exits 1  <-- pinned defect")
    nulls = [f for f in report.findings if f.kind == NULL_CLASS]
    check([f.rows for f in nulls] == [40, 0] and
          [f.severity for f in nulls] == [FAIL, LATENT],
          "the class that holds rows fails and the empty one is latent")
    check("40 of 100 features (40.0%)" in nulls[0].text,
          "the finding says how many features sit in the class")
    check(by_kind[DEFAULTED].rows == 5 and by_kind[DEFAULTED].severity == INFO,
          "a combination with no class is drawn by the default symbol")

    # ---- a null-token class with no rows is latent and passes
    quiet = analyze(renderer, {"X,": 10})
    check(gate(quiet) == 0 and
          all(f.severity != FAIL for f in quiet.findings),
          "null-token classes with no rows are latent, so the run passes")

    # ---- the missing default symbol
    bare = from_rest(rest(["A,x"], default=False))
    report = analyze(bare, {"A,x": 3, "B,y": 7, "C,": 2})
    hidden = [f for f in report.findings if f.kind == HIDDEN]
    check([f.key for f in hidden] == ["B,y", "C,"] and gate(report) == 1,
          "unmatched values with no default symbol fail, largest first  "
          "<-- pinned defect")
    check(NO_DEFAULT not in kinds(report),
          "the latent no-default note is dropped when values are hidden")
    report = analyze(bare, {"A,x": 3})
    check(kinds(report) == [NO_DEFAULT] and gate(report) == 0,
          "no default symbol and every value covered is latent, not a failure")
    report = analyze(bare, None, static=True)
    check(kinds(report) == [NO_DEFAULT] and
          "was not compared" in report.findings[0].text,
          "a static run says it did not compare the data")
    report = analyze(from_rest(rest(["A,x"])), {"A,x": 3})
    check(report.findings == [] and gate(report) == 0,
          "a covered layer with a default symbol is clean")

    # ---- a run that compared nothing is not clean
    report = analyze(renderer, None, incomplete="cut at the limit")
    check(gate(report) == 1 and
          any(f.kind == NULL_CLASS and f.rows is None for f in report.findings)
          and report.findings[0].severity == FAIL,
          "an incomplete run still fails on a token class it can see")
    report = analyze(from_rest(rest(["A,x"])), None, incomplete="cut")
    check(gate(report) == 4, "an incomplete run with no finding exits 4")
    report = analyze(from_rest(rest(["A,x"])), None, static=True)
    check(gate(report) == 0, "a static run with no finding exits 0")

    # ---- REST renderer parsing
    check(from_rest(rest(["a"], fields=("KIND",))).fields == ["KIND"],
          "a one-field renderer has one field")
    check(from_rest(rest(["a"], default=False)).has_default is False,
          "a renderer with no defaultSymbol has no default")
    empty_default = rest(["a"])
    empty_default["defaultSymbol"] = {}
    check(from_rest(empty_default).has_default is False,
          "an empty defaultSymbol object is no default  <-- pinned defect")
    no_delim = rest(["a,b"])
    del no_delim["fieldDelimiter"]
    check(from_rest(no_delim).delimiter == DEFAULT_DELIMITER,
          "a renderer with no fieldDelimiter reads as a comma")
    check(from_rest(rest(["a|b"], delim="|")).delimiter == "|",
          "a named delimiter is kept")
    numeric = rest(["x"])
    numeric["uniqueValueInfos"][0]["value"] = 5
    check(from_rest(numeric).classes == [("5", "Lx")],
          "a numeric class value reads as text")
    bad = rest(["a"])
    bad["type"] = "simple"
    raises(Unsupported, lambda: from_rest(bad),
           "a renderer that is not unique-value is unsupported")
    bad = rest(["a"], fields=())
    raises(Unsupported, lambda: from_rest(bad),
           "a renderer with no field is unsupported")
    bad = rest(["a"])
    del bad["uniqueValueInfos"]
    raises(Unsupported, lambda: from_rest(bad),
           "a renderer with no uniqueValueInfos is unsupported")
    bad = rest(["a"])
    bad["uniqueValueInfos"].append({"label": "no value"})
    raises(Unsupported, lambda: from_rest(bad),
           "a class with no value is unsupported")
    bad["uniqueValueInfos"] = ["text"]
    raises(Unsupported, lambda: from_rest(bad),
           "a class that is not an object is unsupported")

    # ---- CIM (layer file) parsing
    real = from_cim(cim([("A", "<Null>"), ("B", "x")], default=False, use=False))
    check(real.classes == [("A,<Null>", "A, <Null>"), ("B,x", "B, x")],
          "a layer file's fieldValues join into class keys")
    check(real.has_default is False and
          [k for k, _ in real.lints] == [LINT_DEFAULT],
          "a layer file with no defaultSymbol is flagged as a lint")
    check(from_cim(cim([("A", "x")])).has_default is True,
          "a symbol with useDefaultSymbol true is a default")
    off = from_cim(cim([("A", "x")], use=False))
    check(off.has_default is False and off.lints == [],
          "a symbol with useDefaultSymbol absent draws nothing, and is not a "
          "lint  <-- pinned defect")
    blank = cim([("A", "x")])
    blank["defaultSymbol"] = {"type": "CIMSymbolReference"}
    check([k for k, _ in from_cim(blank).lints] == [LINT_DEFAULT],
          "a symbol reference with no symbol is the lint")
    blank["defaultSymbol"] = None
    check(from_cim(blank).has_default is False,
          "a null defaultSymbol is no default")
    check([k for k, _ in from_cim(cim([("A", "x")], expression="")).lints]
          == [LINT_EXPRESSION],
          "an empty valueExpressionInfo is the second lint")
    raises(Unsupported, lambda: from_cim(cim([("A", "x")], expression="$f.A")),
           "a layer file that classifies on Arcade is unsupported")
    raises(Unsupported, lambda: from_cim({"type": "CIMSimpleRenderer"}),
           "a layer file with a simple renderer is unsupported")
    raises(Unsupported, lambda: from_cim(cim([("A", "x")], fields=())),
           "a layer file with no fields is unsupported")
    odd = cim([("A", "x")])
    odd["groups"] = [{"classes": [{"values": [{"fieldValues": "bad"}]}]}, 7]
    check(from_cim(odd).classes == [],
          "malformed groups, classes and values are skipped, not a crash")
    wide = cim([("A", "x")], default=False)
    wide["groups"][0]["classes"][0]["values"].append(
        {"fieldValues": ["A", "y"]})
    check([k for k, _ in from_cim(wide).classes] == ["A,x", "A,y"],
          "a class with two values gives two keys")

    # ---- locating the renderer
    got, oid = extract_renderer(layer(sfha))
    check(got.fields == ["KIND", "SUBKIND"] and oid == "OBJECTID",
          "a REST layer yields its renderer and its object id field")
    doc = layer(sfha)
    del doc["objectIdField"]
    check(extract_renderer(doc)[1] == "OBJECTID",
          "the object id field is found by type when the layer names none")
    doc["fields"] = [{"name": "A", "type": "esriFieldTypeString"}]
    check(extract_renderer(doc)[1] is None,
          "a layer with no object id field yields None")
    doc["objectIdField"] = ["bad"]
    check(extract_renderer(doc)[1] is None,
          "an object id field that is not text yields None")
    check(extract_renderer(sfha)[0].fields == ["KIND", "SUBKIND"],
          "a bare REST renderer is read")
    check(extract_renderer(cim([("A", "x")]))[0].has_default,
          "a bare CIM renderer is read")
    lyrx = {"layerDefinitions": [{"type": "CIMFeatureLayer", "name": "w",
                                  "renderer": cim([("A", "<Null>")])}]}
    check(extract_renderer(lyrx)[0].classes[0][0] == "A,<Null>" and
          extract_renderer(lyrx)[1] is None,
          "a layer file yields its one renderer and no object id field")
    lyrx["layerDefinitions"].append({"renderer": cim([("B", "x")])})
    raises(Unsupported, lambda: extract_renderer(lyrx),
           "a layer file with two renderers is unsupported")
    raises(Unsupported, lambda: extract_renderer({"layerDefinitions": []}),
           "a layer file with no layers is unsupported")
    raises(Unsupported, lambda: extract_renderer({"drawingInfo": {}}),
           "a drawingInfo with no renderer is unsupported")
    raises(Unsupported, lambda: extract_renderer({"drawingInfo": 3}),
           "a drawingInfo that is not an object is unsupported")
    raises(Unsupported, lambda: extract_renderer({"layers": []}),
           "a service root is unsupported, and says to name a layer")

    # ---- the statistics query and its response
    params = stats_params(["KIND", "SUBKIND"], "OBJECTID")
    spec = json.loads(params["outStatistics"])[0]
    check(spec["onStatisticField"] == "OBJECTID" and
          params["groupByFieldsForStatistics"] == "KIND,SUBKIND" and
          params["returnGeometry"] == "false" and params["f"] == "json",
          "the query counts the object id field, grouped by the renderer "
          "fields  <-- pinned defect")

    def stats(rows, **extra):
        doc = {"features": [{"attributes": r} for r in rows]}
        doc.update(extra)
        return doc

    got, cut = parse_stats(stats([
        {"KIND": "A", "SUBKIND": None, COUNT_FIELD: 3},
        {"KIND": "A", "SUBKIND": "", COUNT_FIELD: 2.0}]), renderer)
    check(got == {"A,<Null>": 3, "A,": 2} and cut is False,
          "a null group reads as the token and an empty string stays apart")
    got, cut = parse_stats(stats([
        {"KIND": 5, "SUBKIND": None, COUNT_FIELD: 1},
        {"KIND": 5.0, "SUBKIND": None, COUNT_FIELD: 2}]), renderer)
    check(got == {"5,<Null>": 3},
          "5 and 5.0 fall into one group and their counts add")
    check(parse_stats(stats([], exceededTransferLimit=True), renderer)[1],
          "exceededTransferLimit true marks the response as cut")
    check(parse_stats(stats([], exceededTransferLimit="no"), renderer)[1]
          is False, "only a true exceededTransferLimit counts")
    raises(SourceError, lambda: parse_stats({"features": "x"}, renderer),
           "a response with no features list is refused")
    raises(SourceError, lambda: parse_stats(
        stats([{"KIND": "A", COUNT_FIELD: 1}]), renderer),
        "a row missing a renderer field is refused")
    raises(SourceError, lambda: parse_stats({"features": [5]}, renderer),
           "a row that is not an object is refused")
    for bad_count in (-1, 1.5, "7", True, None):
        raises(SourceError, lambda b=bad_count: parse_stats(stats([
            {"KIND": "A", "SUBKIND": "x", COUNT_FIELD: b}]), renderer),
            "a count of %r is refused" % (bad_count,))

    # ---- the report
    lines = describe(analyze(renderer, groups))
    text = "\n".join(lines)
    check("features: 100 in 4 value combination(s)" in text and
          "VERDICT: 1 finding(s)" in text,
          "the report counts the features, the groups and the findings")
    check(lines[0].startswith("renderer: unique value on KIND, SUBKIND, 3 "
                              "class value(s), default symbol present"),
          "the first line names the fields, the classes and the default")
    crowd = {"A,x": 1, "B,y": 2, "C,": 3}
    check(any("... 1 more not listed" in l for l in
              describe(analyze(bare, crowd), sample=1)),
          "a sample of 1 lists one and counts the rest")
    check(not any("more not listed" in l for l in
                  describe(analyze(bare, crowd), sample=2)),
          "a section no longer than the sample hides nothing")
    lines = describe(analyze(bare, {"A,x": 3}))
    check(lines[-1].startswith("VERDICT: clean."),
          "a covered layer reads as clean")
    lines = describe(analyze(bare, None, static=True))
    check("data: not queried (--static)" in lines and
          "static check" in lines[-1],
          "a static report says the data was not queried")
    lines = describe(analyze(bare, None, incomplete="cut at the limit"))
    check("data: not compared. cut at the limit" in lines and
          lines[-1].startswith("VERDICT: NOT CHECKED"),
          "an incomplete report says NOT CHECKED, never clean")
    lint_report = analyze(real, {"A,<Null>": 1, "B,x": 2, "C,": 4})
    check(gate(lint_report) == 1 and
          [f.key for f in lint_report.findings if f.kind == HIDDEN] == ["C,"],
          "a layer file with no default symbol hides unmatched values")
    lint_only = analyze(from_cim(cim([("A", "x")], default=False)),
                        {"A,x": 1})
    check(gate(lint_only) == 0 and gate(lint_only, True) == 1,
          "a lint passes by default and fails under --fail-on-lint")
    check("VERDICT: 2 finding(s)" in "\n".join(
        describe(analyze(from_cim(cim([("A", "x")], default=False,
                                       expression="")), {"A,x": 1}),
                 fail_on_lint=True)),
          "--fail-on-lint counts each lint as a finding")

    # ---- the output file, which only --apply may write
    out_path = os.path.join(tmp, "findings.csv")
    write_findings(out_path, analyze(renderer, groups))
    with open(out_path, newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    check(rows[0] == list(OUT_COLUMNS) and rows[1][0] == NULL_CLASS and
          rows[1][3] == "40",
          "the findings file has its header and a row per finding")
    write_findings(out_path, analyze(bare, None, static=True))
    with open(out_path, newline="", encoding="utf-8") as handle:
        check(list(csv.reader(handle))[1][3] == "",
              "a finding with no row count writes an empty cell")

    # ---- the url check
    check(url_problem("https://host/rest/services/S/MapServer/0") is None,
          "a plain layer URL is accepted")
    for bad_url, why in (("file:///etc/passwd", "a file URL"),
                         ("ftp://host/x", "an ftp URL"),
                         ("https://", "a URL with no host"),
                         ("https://user:pw@host/x", "a URL with a password"),
                         ("https://host/x?token=abc", "a URL with a query"),
                         ("https://host/x#frag", "a URL with a fragment")):
        check(url_problem(bad_url) is not None, "%s is refused" % why)

    # ---- the stub service, and every network path against it
    class Stub(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status, body, headers=()):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode("utf-8")
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            cfg = self.server.cfg
            parsed = urllib.parse.urlsplit(self.path)
            query = dict(urllib.parse.parse_qsl(parsed.query))
            self.server.log.append((parsed.path, query,
                                    self.headers.get("X-Esri-Authorization")))
            if parsed.path in cfg["raw"]:
                status, headers, body = cfg["raw"][parsed.path]
                return self._send(status, body, headers)
            sent = self.headers.get("X-Esri-Authorization")
            if cfg["token"] and sent != "Bearer " + cfg["token"]:
                return self._send(200, {"error": {
                    "code": 498, "message": "Invalid token: %s" % sent}})
            if parsed.path == "/svc/MapServer/0":
                return self._send(200, cfg["layer"])
            if parsed.path == "/svc/MapServer/0/query":
                spec = json.loads(query["outStatistics"])[0]
                fields = query["groupByFieldsForStatistics"].split(",")
                counted = {}
                for row in cfg["rows"]:
                    key = tuple(row[f] for f in fields)
                    # SQL count(column) skips nulls. The object id is never
                    # null, so counting it counts every row.
                    if row.get(spec["onStatisticField"]) is not None:
                        counted[key] = counted.get(key, 0) + 1
                    else:
                        counted.setdefault(key, 0)
                features = [{"attributes": dict(
                    zip(fields, key), **{spec["outStatisticFieldName"]: n})}
                    for key, n in counted.items()]
                limit = cfg["limit"]
                body = {"features": features[:limit]}
                if len(features) > limit:
                    body["exceededTransferLimit"] = True
                return self._send(200, body)
            return self._send(404, b"not here")

    def start():
        server = HTTPServer(("127.0.0.1", 0), Stub)
        server.cfg = {"raw": {}, "token": None, "limit": 1000,
                      "layer": layer(sfha), "rows": []}
        server.log = []
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server

    def stop(server):
        server.shutdown()
        server.server_close()

    stub = start()
    other = start()
    base = "http://127.0.0.1:%d/svc/MapServer/0" % stub.server_address[1]
    # The stub is local, so no proxy from the environment may stand in front.
    environment = unittest.mock.patch.dict(os.environ, {
        "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"})
    environment.start()
    try:
        # synthetic rows: 40 rows of KIND A with a null SUBKIND, 55 of X with
        # an empty one, 5 of B,y that no class covers
        rows = []
        for index in range(1, 101):
            kind, sub = (("A", None) if index <= 40 else
                         ("X", "") if index <= 95 else ("B", "y"))
            rows.append({"OBJECTID": index, "KIND": kind, "SUBKIND": sub})
        stub.cfg["rows"] = rows

        code, out, err = run_cli(["--url", base])
        check(code == 1 and "40 of 100 features (40.0%)" in out and
              "'B,y': 5 feature(s), drawn by the default symbol" in out,
              "over the wire, a null-token class holding 40 of 100 rows "
              "exits 1  <-- pinned defect")
        sent = [q for p, q, h in stub.log if p.endswith("/query")][0]
        check(json.loads(sent["outStatistics"])[0]["onStatisticField"] ==
              "OBJECTID" and sent["where"] == "1=1",
              "the request counted the object id field, so the 40 null rows "
              "were counted  <-- pinned defect")
        nulls_counted = json.loads(sent["outStatistics"])[0]
        check(nulls_counted["outStatisticFieldName"] == COUNT_FIELD,
              "the request names the count column the tool reads back")

        # the same layer if the count had been on a nullable field
        stub.cfg["layer"] = layer(sfha, oid="SUBKIND")
        code, out, err = run_cli(["--url", base])
        check(code == 0 and "features: 60 in 3" in out and
              "no feature is in it now" in out,
              "the stub counts like SQL, so a count on a nullable field "
              "loses the 40 null rows and reports the layer clean")
        stub.cfg["layer"] = layer(sfha)

        # a layer with no null-token class and a gap
        stub.cfg["layer"] = layer(rest(["A,<Null>"], default=False))
        stub.cfg["layer"]["drawingInfo"]["renderer"][
            "uniqueValueInfos"] = [{"value": "X,", "label": "x"}]
        code, out, err = run_cli(["--url", base, "--sample", "0"])
        check(code == 1 and "(2)" in out and "not listed" in out,
              "values with no class and no default symbol exit 1 over the "
              "wire, and --sample 0 lists none")
        stub.cfg["layer"] = layer(rest(["A,x", "X,", "B,y"]))
        code, out, err = run_cli(["--url", base])
        check(code == 0 and "drawn by the default symbol" in out,
              "values with no class but a default symbol pass over the wire")

        stub.cfg["layer"] = layer(rest(["A,<Null>", "X,", "B,y"],
                                       default=False))
        stub.cfg["layer"]["drawingInfo"]["renderer"]["uniqueValueInfos"] = [
            {"value": "X,", "label": "x"}, {"value": "B,y", "label": "b"}]
        stub.cfg["rows"] = [r for r in rows if r["KIND"] != "A"]
        code, out, err = run_cli(["--url", base])
        check(code == 0 and "VERDICT: clean." in out,
              "a covered layer exits 0 over the wire")
        stub.cfg["rows"] = rows

        # the token travels in a header, and never anywhere else
        secret = "s3cr3t-token-value"
        os.environ["RENDERGAP_TEST_TOKEN"] = secret
        stub.cfg["token"] = secret
        stub.cfg["layer"] = layer(sfha)
        stub.log[:] = []
        out_file = os.path.join(tmp, "token-run.csv")
        code, out, err = run_cli(["--url", base, "--token-env",
                                  "RENDERGAP_TEST_TOKEN", "--out", out_file,
                                  "--apply"])
        with open(out_file, encoding="utf-8") as handle:
            written = handle.read()
        check(code == 1 and all(h == "Bearer " + secret for _, _, h in
                                stub.log) and len(stub.log) == 2,
              "the token is sent as an X-Esri-Authorization bearer header on "
              "both requests")
        check(all(secret not in q.values() for _, q, _ in stub.log) and
              all(secret not in p for p, _, _ in stub.log),
              "the token is in no URL or query string")
        check(secret not in out + err + written,
              "the token is in neither the output, the errors nor the "
              "findings file")
        os.environ["RENDERGAP_TEST_TOKEN"] = "wrong-token-value"
        code, out, err = run_cli(["--url", base, "--token-env",
                                  "RENDERGAP_TEST_TOKEN"])
        check(code == 2 and "code 498" in err and
              "wrong-token-value" not in out + err and "***" in err,
              "a server that echoes the rejected token has it redacted from "
              "the error  <-- pinned defect")
        code, out, err = run_cli(["--url", base])
        check(code == 2 and "code 498" in err,
              "no token against a secured service is an error, exit 2, not "
              "a verdict")
        del os.environ["RENDERGAP_TEST_TOKEN"]
        stub.cfg["token"] = None

        # a redirect is refused, so the header goes nowhere else
        other.log[:] = []
        stub.cfg["raw"]["/svc/MapServer/0"] = (
            302, [("Location", "http://127.0.0.1:%d/svc/MapServer/0"
                   % other.server_address[1])], b"")
        os.environ["RENDERGAP_TEST_TOKEN"] = secret
        code, out, err = run_cli(["--url", base, "--token-env",
                                  "RENDERGAP_TEST_TOKEN"])
        check(code == 2 and "HTTP 302" in err and other.log == [],
              "a redirect is refused and the second host never sees the "
              "request  <-- pinned defect")
        del os.environ["RENDERGAP_TEST_TOKEN"]

        # failures of the wire itself
        stub.cfg["raw"]["/svc/MapServer/0"] = (
            200, [], {"error": {"code": 400, "message": "Invalid URL"}})
        code, out, err = run_cli(["--url", base])
        check(code == 2 and "code 400, Invalid URL" in err,
              "a JSON error body under HTTP 200 is an error, not a layer  "
              "<-- pinned defect")
        stub.cfg["raw"]["/svc/MapServer/0"] = (
            200, [], {"error": "plain text error"})
        code, out, err = run_cli(["--url", base])
        check(code == 2 and "plain text error" in err,
              "an error that is a bare string is still an error")
        stub.cfg["raw"]["/svc/MapServer/0"] = (500, [], b"boom")
        code, out, err = run_cli(["--url", base])
        check(code == 2 and "HTTP 500" in err, "an HTTP 500 exits 2")
        stub.cfg["raw"]["/svc/MapServer/0"] = (200, [], b"<html>login</html>")
        code, out, err = run_cli(["--url", base])
        check(code == 2 and "is not JSON" in err,
              "an HTML login page is not mistaken for a layer")
        stub.cfg["raw"]["/svc/MapServer/0"] = (200, [], b"\xff\xfe")
        code, out, err = run_cli(["--url", base])
        check(code == 2 and "is not JSON" in err,
              "bytes that are not UTF-8 are not mistaken for a layer")
        stub.cfg["raw"]["/svc/MapServer/0"] = (200, [], b"[1, 2]")
        code, out, err = run_cli(["--url", base])
        check(code == 2 and "not a JSON object" in err,
              "a JSON array is not a layer")
        real_max = globals()["MAX_BYTES"]
        try:
            globals()["MAX_BYTES"] = 10
            stub.cfg["raw"]["/svc/MapServer/0"] = (200, [], b"x" * 50)
            code, out, err = run_cli(["--url", base])
        finally:
            globals()["MAX_BYTES"] = real_max
        check(code == 2 and "over 10 bytes" in err,
              "a response over the byte cap is refused unread")
        del stub.cfg["raw"]["/svc/MapServer/0"]
        code, out, err = run_cli(["--url", base[:-1] + "9"])
        check(code == 2 and "HTTP 404" in err, "an HTTP 404 exits 2")
        dead = "http://127.0.0.1:1/svc/MapServer/0"
        code, out, err = run_cli(["--url", dead])
        check(code == 2 and "could not reach" in err,
              "a refused connection exits 2")

        # the query side
        stub.cfg["raw"]["/svc/MapServer/0/query"] = (
            200, [], {"error": {"code": 400, "message": "no statistics"}})
        code, out, err = run_cli(["--url", base])
        check(code == 2 and "no statistics" in err,
              "a service that cannot run statistics says so, exit 2")
        del stub.cfg["raw"]["/svc/MapServer/0/query"]

        stub.cfg["limit"] = 2
        code, out, err = run_cli(["--url", base])
        check(code == 1 and "NOT CHECKED" not in out and
              "exceededTransferLimit" in out and "rows not counted" in out,
              "a response cut at the limit still fails on a token class "
              "it can see, and says the data was not compared")
        stub.cfg["layer"] = layer(rest(["X,"]))
        code, out, err = run_cli(["--url", base])
        check(code == 4 and "VERDICT: NOT CHECKED" in out and
              "exceededTransferLimit" in out,
              "a response cut at the limit with nothing else flagged exits "
              "4, never 0  <-- pinned defect")
        stub.cfg["limit"] = 1000
        stub.cfg["rows"] = []
        code, out, err = run_cli(["--url", base])
        check(code == 4 and "no rows" in out,
              "a layer with no rows compared nothing, so exit 4  "
              "<-- pinned defect")
        stub.cfg["rows"] = rows

        stub.cfg["layer"] = {"drawingInfo": {"renderer": rest(["A,x"])},
                             "fields": [{"name": "A", "type": "x"}]}
        code, out, err = run_cli(["--url", base])
        check(code == 4 and "no object id field" in out,
              "a layer that names no object id field is not counted on a "
              "nullable one")
        stub.cfg["layer"] = layer({"type": "simple", "symbol": sym})
        code, out, err = run_cli(["--url", base])
        check(code == 4 and "not uniqueValue" in out and
              "VERDICT: NOT CHECKED" in out,
              "a simple renderer exits 4, it is not called clean")
        stub.cfg["layer"] = layer(sfha)

        # --out writes only under --apply
        out_file = os.path.join(tmp, "wire.csv")
        code, out, err = run_cli(["--url", base, "--out", out_file])
        check(code == 1 and not os.path.exists(out_file) and
              "Check only" in out,
              "without --apply the findings file is not written")
        code, out, err = run_cli(["--url", base, "--out", out_file,
                                  "--apply"])
        check(code == 1 and os.path.exists(out_file) and
              ("wrote " + out_file) in out,
              "with --apply the findings file is written")
        target = os.path.join(tmp, "no-such-dir", "f.csv")
        code, out, err = run_cli(["--url", base, "--out", target, "--apply"])
        check(code == 2 and "could not write" in err,
              "an output path that cannot be written exits 2")

        # offline: saved layer and statistics files
        layer_file = tmpfile("layer.json", json.dumps(layer(sfha)))
        stats_file = tmpfile("stats.json", json.dumps(stats([
            {"KIND": "A", "SUBKIND": None, COUNT_FIELD: 40},
            {"KIND": "X", "SUBKIND": "", COUNT_FIELD: 60}])))
        code, out, err = run_cli(["--layer-json", layer_file,
                                  "--stats-json", stats_file])
        check(code == 1 and "40 of 100 features (40.0%)" in out,
              "saved files give the same finding as the wire")
        code, out, err = run_cli(["--layer-json", layer_file, "--static"])
        check(code == 1 and "rows not counted" in out and
              "data: not queried" in out,
              "--static still fails on a token class it can see")
        clean_layer = tmpfile("clean.json", json.dumps(layer(rest(["X,"]))))
        code, out, err = run_cli(["--layer-json", clean_layer, "--static"])
        check(code == 0 and "static check" in out,
              "--static on a clean renderer exits 0 and says it was static")
        lyrx_file = tmpfile("l.lyrx", "\ufeff" + json.dumps(
            {"layerDefinitions": [{"renderer": cim([("A", "<Null>")],
                                                    default=False,
                                                    use=False)}]}))
        code, out, err = run_cli(["--layer-json", lyrx_file, "--static"])
        check(code == 1 and "lint, an empty default symbol" in out,
              "a layer file with a byte order mark is read, and its lint "
              "is shown")
        code, out, err = run_cli(["--layer-json", lyrx_file, "--static",
                                  "--fail-on-lint"])
        check(code == 1, "--fail-on-lint is accepted")
        lyrx_ok = tmpfile("ok.lyrx", json.dumps(
            {"layerDefinitions": [{"renderer": cim([("A", "x")],
                                                    default=False)}]}))
        code, out, err = run_cli(["--layer-json", lyrx_ok, "--static"])
        check(code == 0, "a lint alone does not fail the run")
        code, out, err = run_cli(["--layer-json", lyrx_ok, "--static",
                                  "--fail-on-lint"])
        check(code == 1 and "VERDICT: 1 finding(s)" in out,
              "--fail-on-lint fails the run on a lint")
    finally:
        stop(stub)
        stop(other)
        environment.stop()

    # ---- bad files and bad usage
    code, out, err = run_cli(["--layer-json", os.path.join(tmp, "nope.json"),
                              "--static"])
    check(code == 2 and "nope.json" in err, "a missing file exits 2")
    bad_file = tmpfile("bad.json", "{not json")
    code, out, err = run_cli(["--layer-json", bad_file, "--static"])
    check(code == 2 and "is not JSON" in err, "a file that is not JSON exits 2")
    arr_file = tmpfile("arr.json", "[1]")
    code, out, err = run_cli(["--layer-json", arr_file, "--static"])
    check(code == 2 and "not a JSON object" in err,
          "a file that is a JSON array exits 2")
    err_file = tmpfile("err.json", json.dumps({"error": {"code": 1,
                                                          "message": "m"}}))
    code, out, err = run_cli(["--layer-json", err_file, "--static"])
    check(code == 2 and "code 1, m" in err,
          "a saved error response is an error, not a layer")
    bad_stats = tmpfile("bad-stats.json", json.dumps({"features": 5}))
    code, out, err = run_cli(["--layer-json", layer_file,
                              "--stats-json", bad_stats])
    check(code == 2 and "no features list" in err,
          "a malformed statistics file exits 2")
    root_file = tmpfile("root.json", json.dumps({"layers": []}))
    code, out, err = run_cli(["--layer-json", root_file, "--static"])
    check(code == 4 and "name a layer URL" in out,
          "a service root exits 4 and says to name a layer")

    usage = (
        (["--url", "https://h/x/0", "--layer-json", layer_file], "both sources"),
        ([], "no source"),
        (["--layer-json", layer_file], "no data choice"),
        (["--layer-json", layer_file, "--static", "--stats-json", stats_file],
         "both static and stats"),
        (["--url", "https://h/x/0", "--static"], "static with a url"),
        (["--url", "https://h/x/0", "--stats-json", stats_file],
         "stats file with a url"),
        (["--url", "https://h/x?token=a"], "a token in the url"),
        (["--layer-json", layer_file, "--static", "--token-env", "X"],
         "a token without a url"),
        (["--url", "https://h/x/0", "--token-env", "RENDERGAP_UNSET_VAR"],
         "an unset token variable"),
        (["--layer-json", layer_file, "--static", "--sample", "-1"],
         "a negative sample"),
        (["--layer-json", layer_file, "--static", "--apply"],
         "--apply without --out"),
        (["--layer-json", layer_file, "--static", "--out", layer_file,
          "--apply"], "--out naming the input"),
        (["--layer-json", layer_file, "--stats-json", layer_file, "--out",
          layer_file], "--out naming an input on a dry run"),
        (["--layer-json", layer_file, "--stats-json", stats_file, "--out",
          stats_file], "--out naming the statistics file"),
        (["--layer-json", layer_file, "--static", "--bogus"], "an unknown flag"),
    )
    for argv, why in usage:
        code, out, err = run_cli(argv)
        check(code == 64 and out == "", "%s is a usage error, exit 64, with "
              "nothing on stdout" % why)

    with unittest.mock.patch.dict(os.environ, {"RENDERGAP_TEST_TOKEN": "x"}):
        code, out, err = run_cli(["--url", "http://example.invalid/x/0",
                                  "--token-env", "RENDERGAP_TEST_TOKEN"])
    check(code == 64 and "only over https" in err and out == "",
          "a token is refused over plain http to a remote host, before any "
          "request is made  <-- pinned defect")

    # ---- the parser refuses a prefix of the write flag
    for prefix in ("--ap", "--app", "--appl"):
        code, out, err = run_cli(["--layer-json", layer_file, "--static",
                                  "--out", os.path.join(tmp, "p.csv"), prefix])
        check(code == 64 and not os.path.exists(os.path.join(tmp, "p.csv")),
              "a unique prefix %s of --apply is REFUSED by the parser and "
              "writes nothing  <-- pinned defect" % prefix)
    code, out, err = run_cli(["--layer-json", layer_file, "--sta"])
    check(code == 64, "a prefix --sta of --static is refused too")
    code, out, err = run_cli(["--layer-json", layer_file, "--static",
                              "--sam", "2"])
    check(code == 64, "a prefix --sam of --sample is refused too")
    check(_parse([]).apply is False and _parse(["--apply"]).apply is True,
          "--apply is off unless it is named in full")

    # ---- the process: a real child, exit codes and encodings
    child = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--layer-json",
         layer_file, "--stats-json", stats_file],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    check(child.returncode == 1 and b"VERDICT: 1 finding(s)" in child.stdout,
          "run as a program, the verdict arrives and the exit code is 1")
    uni = tmpfile("uni.json", json.dumps(layer(rest(["\u0141,<Null>"])),
                                         ensure_ascii=False))
    child = subprocess.run(
        [sys.executable, os.path.abspath(__file__), "--layer-json", uni,
         "--static"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=dict(os.environ, PYTHONIOENCODING="ascii"))
    check(child.returncode == 1 and b"Traceback" not in child.stderr and
          b"'?,<Null>'" in child.stdout,
          "a class value the console cannot encode prints as ? and the "
          "verdict still arrives  <-- pinned defect")

    calls = []

    class Reconfigurable(io.StringIO):
        def reconfigure(self, **kw):
            calls.append(kw)

    with contextlib.redirect_stdout(Reconfigurable()), \
            contextlib.redirect_stderr(Reconfigurable()):
        main(["--help"])
    check(calls == [{"errors": "replace"}] * 2,
          "main reconfigures stdout and stderr to replace what they cannot "
          "encode")

    # A crash is not a finding.
    real_analyze = globals()["analyze"]

    def boom(*args, **kw):
        raise RuntimeError("probe")

    try:
        globals()["analyze"] = boom
        code, out, err = run_cli(["--layer-json", layer_file, "--static"])
    finally:
        globals()["analyze"] = real_analyze
    check(code == 70 and "unexpected RuntimeError: probe" in err and
          "VERDICT" not in out,
          "an unexpected exception exits 70, not the 1 that means a finding  "
          "<-- pinned defect")

    # The temp directory goes even when the body raises.
    seen = []

    def exploding(path):
        seen.append(path)
        raise RuntimeError("probe")

    real_body = globals()["_self_test"]
    try:
        globals()["_self_test"] = exploding
        try:
            self_test()
        except RuntimeError:
            seen.append("raised")
    finally:
        globals()["_self_test"] = real_body
    check(len(seen) == 2 and seen[1] == "raised"
          and not os.path.exists(seen[0]),
          "a self-test that raises still removes its temp directory  "
          "<-- pinned defect")

    # ---- the harness itself. A check() that cannot record a failure would
    # report every defect above as a pass.
    quiet_out = sys.stdout
    sys.stdout = io.StringIO()
    mark = len(failed)
    try:
        check(False, "probe: a false condition must be recorded as a failure")
        raises(ValueError, lambda: None, "probe: no error must fail")
        raises(ValueError, lambda: [][0], "probe: the wrong exception must fail")
    finally:
        sys.stdout = quiet_out
    probe = failed[mark:]
    del failed[mark:]
    check(len(probe) == 3,
          "check() and raises() really do record a failure  <-- pinned defect")
    raises(ValueError, lambda: (_ for _ in ()).throw(ValueError("x")),
           "and raises() accepts the exception it is looking for")

    def summary(passed_count, failures):
        print("-" * 68)
        total = passed_count + len(failures)
        if failures:
            print("%d assertions, %d failed" % (total, len(failures)))
            for f in failures:
                print("  FAILED: %s" % f)
            return 1
        print("%d assertions, 0 failed" % total)
        return 0

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        red = summary(1, ["probe one", "probe two"])
    check(red == 1 and "3 assertions, 2 failed" in buf.getvalue()
          and "  FAILED: probe two" in buf.getvalue(),
          "the footer reports failures by count and by name, and exits 1  "
          "<-- pinned defect")

    # ---- importing the module runs nothing
    spec = importlib.util.spec_from_file_location(
        "rendergap_imported", os.path.abspath(__file__))
    imported = importlib.util.module_from_spec(spec)
    buf = io.StringIO()
    cache_before = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        with contextlib.redirect_stdout(buf):
            spec.loader.exec_module(imported)
    finally:
        sys.dont_write_bytecode = cache_before
    check(buf.getvalue() == "" and imported.gate(
        imported.analyze(imported.from_rest(rest(["a,b"])), {"a,b": 1})) == 0,
        "importing the module prints nothing and exposes the core")

    return summary(passed[0], failed)


# ----------------------------------------------------------------------- cli

def _parse(argv):
    ap = argparse.ArgumentParser(
        prog="rendergap.py",
        description="Flag unique-value classes that carry the <Null> token "
                    "and values that no class or default symbol covers.",
        epilog="Nothing is written without --apply. The tool only reads a "
               "service.",
        allow_abbrev=False,
    )
    ap.add_argument("--url", help="a layer URL that ends in the layer number, "
                    "with no query string")
    ap.add_argument("--layer-json", dest="layer_json",
                    help="a saved layer response, a layer file or a renderer")
    ap.add_argument("--stats-json", dest="stats_json",
                    help="a saved group-by response, with the count column "
                         "named %s" % COUNT_FIELD)
    ap.add_argument("--static", action="store_true",
                    help="check the renderer alone, with no data")
    ap.add_argument("--token-env", dest="token_env",
                    help="the name of an environment variable that holds a "
                         "token. It is sent in a header, never in the URL.")
    ap.add_argument("--fail-on-lint", dest="fail_on_lint",
                    action="store_true",
                    help="exit 1 on a lint as well as a finding")
    ap.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                    help="how many findings to list under each heading "
                         "(default %d)" % DEFAULT_SAMPLE)
    ap.add_argument("--out", help="path for the findings CSV")
    ap.add_argument("--apply", action="store_true",
                    help="write --out. Without this nothing is written.")
    ap.add_argument("--self-test", dest="self_test", action="store_true",
                    help="run the offline assertions and exit")
    return ap.parse_args(argv)


def _same_file(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(
        os.path.realpath(b))


def _usage_problem(args):
    """Why the arguments are refused, or None."""
    if bool(args.url) == bool(args.layer_json):
        return "name exactly one of --url and --layer-json"
    if args.url:
        if args.static or args.stats_json:
            return ("--url always queries the data, so --static and "
                    "--stats-json do not apply")
        problem = url_problem(args.url)
        if problem:
            return problem
    elif bool(args.static) == bool(args.stats_json):
        return ("with --layer-json, name exactly one of --stats-json and "
                "--static")
    if args.token_env:
        if not args.url:
            return "--token-env needs --url"
        if not os.environ.get(args.token_env):
            return "the environment variable %s is not set" % args.token_env
        parts = urllib.parse.urlsplit(args.url)
        if parts.scheme != "https" and parts.hostname not in LOOPBACK:
            return "a token is sent only over https, or to a loopback address"
    if args.sample < 0:
        return "--sample cannot be negative"
    if args.apply and not args.out:
        return "--apply needs --out"
    if args.out:
        for source in (args.layer_json, args.stats_json):
            if source and _same_file(args.out, source):
                return "--out %s is also an input file. Name a new file." % \
                    args.out
    return None


def _collect(args, token):
    if args.url:
        layer = get_json(args.url.rstrip("/"), {"f": "json"}, token)
    else:
        layer = read_json(args.layer_json)
    renderer, oid = extract_renderer(layer)
    stats = None
    if args.url:
        if not oid:
            raise Unsupported("the layer names no object id field, and "
                              "counting any other field skips the nulls")
        stats = get_json(args.url.rstrip("/") + "/query",
                         stats_params(renderer.fields, oid), token)
    elif args.stats_json:
        stats = read_json(args.stats_json)
    groups = incomplete = None
    if stats is not None:
        groups, cut = parse_stats(stats, renderer)
        if cut:
            groups = None
            incomplete = ("the service cut its answer at its record limit "
                          "(exceededTransferLimit), so the counts are partial")
        elif not sum(groups.values()):
            groups = None
            incomplete = "the layer has no rows, so there is nothing to compare"
    return analyze(renderer, groups, incomplete, args.static)


def _tolerate_odd_characters():
    """Make print() unable to fail on a character the console cannot encode."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(errors="replace")


def main(argv=None):
    """Run the CLI. An error this code did not anticipate exits 70, because 1
    is the code a scheduled job reads as 'a finding'."""
    _tolerate_odd_characters()
    try:
        return _run(argv)
    except Exception as exc:
        print("error: unexpected %s: %s. This is a fault in the tool, not a "
              "finding about the data." % (type(exc).__name__, exc),
              file=sys.stderr)
        traceback.print_exc()
        return 70


def _run(argv):
    try:
        args = _parse(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        # argparse exits 2 on a flag it refuses, and 2 here means a source
        # could not be read. A mistyped --ap is a usage error, so it gets 64.
        return 64 if exc.code == 2 else exc.code

    if args.self_test:
        return self_test()

    problem = _usage_problem(args)
    if problem:
        print("error: %s" % problem, file=sys.stderr)
        return 64

    token = os.environ[args.token_env] if args.token_env else None
    source = args.url or args.layer_json
    try:
        report = _collect(args, token)
    except Unsupported as exc:
        print("rendergap: %s" % source)
        print("\nVERDICT: NOT CHECKED. %s." % exc)
        return 4
    except (SourceError, IOError, OSError) as exc:
        print("error: %s" % _redact(str(exc), token), file=sys.stderr)
        return 2

    print("rendergap: %s" % source)
    for line in describe(report, args.sample, args.fail_on_lint):
        print(line)

    if args.out:
        if args.apply:
            try:
                write_findings(args.out, report)
            except (IOError, OSError, csv.Error) as exc:
                print("error: could not write %s: %s" % (args.out, exc),
                      file=sys.stderr)
                return 2
            print("\nwrote %s" % args.out)
        else:
            print("\nCheck only. %s was not written. Re-run with --apply."
                  % args.out)

    return gate(report, args.fail_on_lint)


if __name__ == "__main__":
    sys.exit(main())
