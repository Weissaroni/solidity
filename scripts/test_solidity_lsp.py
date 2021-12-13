#!/usr/bin/env python3

import argparse
import fnmatch
import json
import os
import subprocess

from typing import Any, List, Optional, Union

import colorama # Enables the use of SGR & CUP terminal VT sequences on Windows.
from deepdiff import DeepDiff

# {{{ JsonRpcProcess
class BadHeader(Exception):
    def __init__(self, msg: str):
        super().__init__("Bad header: " + msg)

class MyEncoder(json.JSONEncoder):
    """
    Encodes an object in JSON
    """
    def default(self, o):
        return o.__dict__

class JsonRpcProcess:
    exe_path: str
    exe_args: List[str]
    process: subprocess.Popen
    trace_io: bool

    def __init__(self, exe_path: str, exe_args: List[str], trace_io: bool = True):
        self.exe_path = exe_path
        self.exe_args = exe_args
        self.trace_io = trace_io

    def __enter__(self):
        self.process = subprocess.Popen(
            [self.exe_path, *self.exe_args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        return self

    def __exit__(self, exception_type, exception_value, traceback) -> None:
        self.process.kill()
        self.process.wait(timeout=2.0)

    def trace(self, topic: str, message: str) -> None:
        if self.trace_io:
            print(f"{SGR_TRACE}{topic}:{SGR_RESET} {message}")

    def receive_message(self) -> Union[None, dict]:
        # Note, we should make use of timeout to avoid infinite blocking if nothing is received.
        CONTENT_LENGTH_HEADER = "Content-Length: "
        CONTENT_TYPE_HEADER = "Content-Type: "
        if self.process.stdout == None:
            return None
        message_size = None
        while True:
            # read header
            line = self.process.stdout.readline()
            if line == '':
                # server quit
                return None
            line = line.decode("utf-8")
            if not line.endswith("\r\n"):
                raise BadHeader("missing newline")
            # remove the "\r\n"
            line = line[:-2]
            if line == "":
                break # done with the headers
            if line.startswith(CONTENT_LENGTH_HEADER):
                line = line[len(CONTENT_LENGTH_HEADER):]
                if not line.isdigit():
                    raise BadHeader("size is not int")
                message_size = int(line)
            elif line.startswith(CONTENT_TYPE_HEADER):
                # nothing todo with type for now.
                pass
            else:
                raise BadHeader("unknown header")
        if message_size is None:
            raise BadHeader("missing size")
        rpc_message = self.process.stdout.read(message_size).decode("utf-8")
        json_object = json.loads(rpc_message)
        self.trace('receive_message', json.dumps(json_object, indent=4, sort_keys=True))
        return json_object

    def send_message(self, method_name: str, params: Optional[dict]) -> None:
        if self.process.stdin == None:
            return
        message = {
            'jsonrpc': '2.0',
            'method': method_name,
            'params': params
        }
        json_string = json.dumps(obj=message, cls=MyEncoder)
        rpc_message = f"Content-Length: {len(json_string)}\r\n\r\n{json_string}"
        self.trace(f'send_message ({method_name})', json.dumps(message, indent=4, sort_keys=True))
        self.process.stdin.write(rpc_message.encode("utf-8"))
        self.process.stdin.flush()

    def call_method(self, method_name: str, params: Optional[dict]) -> Any:
        self.send_message(method_name, params)
        return self.receive_message()

    def send_notification(self, name: str, params: Optional[dict] = None) -> None:
        self.send_message(name, params)

# }}}

SGR_RESET = '\033[m'
SGR_TRACE = '\033[1;36m'
SGR_NOTICE = '\033[1;35m'
SGR_TEST_BEGIN = '\033[1;33m'
SGR_ASSERT_BEGIN = '\033[1;34m'
SGR_STATUS_OKAY = '\033[1;32m'
SGR_STATUS_FAIL = '\033[1;31m'

class ExpectationFailed(Exception):
    def __init__(self, actual, expected):
        self.actual = actual
        self.expected = expected
        diff = DeepDiff(actual, expected)
        super().__init__(
            f"Expectation failed.\n\tExpected {expected}\n\tbut got {actual}.\n\t{diff}"
        )

def create_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Solidity LSP Test suite")
    parser.set_defaults(trace_io=False)
    parser.add_argument(
        "-T, --trace-io",
        dest="trace_io",
        action="store_true",
        help="Be more verbose by also printing assertions."
    )
    parser.set_defaults(print_assertions=False)
    parser.add_argument(
        "-v, --print-assertions",
        dest="print_assertions",
        action="store_true",
        help="Be more verbose by also printing assertions."
    )
    parser.add_argument(
        "-t, --test-pattern",
        dest="test_pattern",
        type=str,
        default="*",
        help="Filters all available tests by matching against this test pattern (using globbing)",
        nargs="?"
    )
    parser.add_argument(
        "solc_path",
        type=str,
        default="solc",
        help="Path to solc binary to test against",
        nargs="?"
    )
    parser.add_argument(
        "project_root_dir",
        type=str,
        default=f"{os.path.dirname(os.path.realpath(__file__))}/..",
        help="Path to Solidity project's root directory (must be fully qualified).",
        nargs="?"
    )
    return parser

class SolidityLSPTestSuite: # {{{
    tests_passed: int = 0
    tests_failed: int = 0
    assertion_count: int = 0   # number of total assertions executed so far
    assertions_passed: int = 0
    assertions_failed: int = 0
    print_assertions: bool = False
    trace_io: bool = False
    test_pattern: str

    def __init__(self):
        colorama.init()
        args = create_cli_parser().parse_args()
        self.solc_path = args.solc_path
        self.project_root_dir = os.path.realpath(args.project_root_dir) + "/test/libsolidity/lsp"
        self.project_root_uri = "file://" + self.project_root_dir
        self.print_assertions = args.print_assertions
        self.trace_io = args.trace_io
        self.test_pattern = args.test_pattern

        print(f"{SGR_NOTICE}test pattern: {self.test_pattern}{SGR_RESET}")

    def main(self) -> int:
        """
        Runs all test cases.
        Returns 0 on success and the number of failing assertions (capped to 127) otherwise.
        """
        all_tests = sorted(
            [
                name for name in dir(SolidityLSPTestSuite)
                if callable(getattr(SolidityLSPTestSuite, name)) and name.startswith("test_")
            ]
        )
        filtered_tests = fnmatch.filter(all_tests, self.test_pattern)
        for method_name in filtered_tests:
            test_fn = getattr(self, method_name)
            title: str = test_fn.__name__[5:]
            print(f"{SGR_TEST_BEGIN}Testing {title} ...{SGR_RESET}")
            try:
                with JsonRpcProcess(self.solc_path, ["--lsp"], trace_io=self.trace_io) as solc:
                    test_fn(solc)
                    self.tests_passed = self.tests_passed + 1
            except ExpectationFailed as e:
                print(f"{e}")
                self.tests_failed = self.tests_failed + 1

        print(
            f"\nSummary:\n\n"
            f"  Test cases: {self.tests_passed} passed, {self.tests_failed} failed\n"
            f"  Assertions: {self.assertions_passed} passed, {self.assertions_failed} failed\n"
        )

        return min(self.assertions_failed, 127)

    def setup_lsp(self, lsp: JsonRpcProcess, expose_project_root=True):
        """
        Prepares the solc LSP server by calling `initialize`,
        and `initialized` methods.
        """
        project_root_uri = "file://" + self.project_root_dir
        params = {
            'processId': None,
            'rootPath': self.project_root_dir,
            'rootUri': project_root_uri,
            'trace': 'off',
            'workspaceFolders': [
                {'name': 'solidity-lsp', 'uri': project_root_uri}
            ],
            'initializationOptions': {},
            'capabilities': {
                'textDocument': {
                    'publishDiagnostics': {'relatedInformation': True}
                },
                'workspace': {
                    'applyEdit': True,
                    'configuration': True,
                    'didChangeConfiguration': {'dynamicRegistration': True},
                    'workspaceEdit': {'documentChanges': True},
                    'workspaceFolders': True
                }
            }
        }
        if expose_project_root == False:
            params['rootUri'] = None
            params['rootPath'] = None
        lsp.call_method('initialize', params)
        lsp.send_notification('initialized')

    # {{{ helpers
    def get_test_file_path(self, test_case_name):
        return f"{self.project_root_dir}/{test_case_name}.sol"

    def get_test_file_uri(self, test_case_name):
        return "file://" + self.get_test_file_path(test_case_name)

    def get_test_file_contents(self, test_case_name):
        """
        Reads the file contents from disc for a given test case.
        The `test_case_name` will be the basename of the file
        in the test path (test/libsolidity/lsp).
        """
        with open(self.get_test_file_path(test_case_name), mode="r", encoding="utf-8") as f:
            return f.read()

    def require_params_for_method(self, method_name: str, message: dict) -> Any:
        """
        Ensures the given RPC message does contain the
        field 'method' with the given method name,
        and then returns its passed params.
        An exception is raised on expectation failures.
        """
        assert message is not None
        if 'error' in message.keys():
            code = message['error']["code"]
            text = message['error']['message']
            raise RuntimeError(f"Error {code} received. {text}")
        if not 'method' in message.keys():
            raise RuntimeError("No method received but something else.")
        self.expect_equal(message['method'], method_name, "Ensure expected method name")
        return message['params']

    def wait_for_diagnostics(self, solc: JsonRpcProcess, count: int) -> List[Any]:
        """
        Return `count` number of published diagnostic reports sorted by file URI.
        """
        reports = []
        for _ in range(0, count):
            message = solc.receive_message()
            assert message is not None # This can happen if the server aborts early.
            reports.append(
                self.require_params_for_method(
                    'textDocument/publishDiagnostics',
                    message,
                )
            )
        return sorted(reports, key=lambda x: x['uri'])

    def open_file_and_wait_for_diagnostics(
        self,
        solc_process: JsonRpcProcess,
        test_case_name: str,
        max_diagnostic_reports: int = 1
    ) -> List[Any]:
        """
        Opens file for given test case and waits for diagnostics to be published.
        """
        assert max_diagnostic_reports > 0
        solc_process.send_message(
            'textDocument/didOpen',
            {
                'textDocument':
                {
                    'uri': self.get_test_file_uri(test_case_name),
                    'languageId': 'Solidity',
                    'version': 1,
                    'text': self.get_test_file_contents(test_case_name)
                }
            }
        )
        return self.wait_for_diagnostics(solc_process, max_diagnostic_reports)

    def expect_equal(self, actual, expected, description="Equality") -> None:
        self.assertion_count = self.assertion_count + 1
        prefix = f"[{self.assertion_count}] {SGR_ASSERT_BEGIN}{description}: "
        diff = DeepDiff(actual, expected)
        if len(diff) == 0:
            self.assertions_passed = self.assertions_passed + 1
            if self.print_assertions:
                print(prefix + SGR_STATUS_OKAY + 'OK' + SGR_RESET)
            return

        # Failed assertions are always printed.
        self.assertions_failed = self.assertions_failed + 1
        print(prefix + SGR_STATUS_FAIL + 'FAILED' + SGR_RESET)
        raise ExpectationFailed(actual, expected)

    def expect_diagnostic(self, diagnostic, code: int, lineNo: int, startColumn: int, endColumn: int):
        self.expect_equal(diagnostic['code'], code, f'diagnostic: {code}')
        self.expect_equal(
            diagnostic['range'],
            {
                'end': {'character': endColumn, 'line': lineNo},
                'start': {'character': startColumn, 'line': lineNo}
            },
            "diagnostic: check range"
        )
    # }}}

    # {{{ actual tests
    def test_publish_diagnostics_warnings(self, solc: JsonRpcProcess) -> None:
        self.setup_lsp(solc)
        TEST_NAME = 'publish_diagnostics_1'
        published_diagnostics = self.open_file_and_wait_for_diagnostics(solc, TEST_NAME)

        self.expect_equal(len(published_diagnostics), 1, "One published_diagnostics message")
        report = published_diagnostics[0]

        self.expect_equal(report['uri'], self.get_test_file_uri(TEST_NAME), "Correct file URI")
        diagnostics = report['diagnostics']

        self.expect_equal(len(diagnostics), 3, "3 diagnostic messages")
        self.expect_diagnostic(diagnostics[0], code=6321, lineNo=13, startColumn=44, endColumn=48)
        self.expect_diagnostic(diagnostics[1], code=2072, lineNo= 7, startColumn= 8, endColumn=19)
        self.expect_diagnostic(diagnostics[2], code=2072, lineNo=15, startColumn= 8, endColumn=20)

    def test_publish_diagnostics_errors(self, solc: JsonRpcProcess) -> None:
        self.setup_lsp(solc)
        TEST_NAME = 'publish_diagnostics_2'
        published_diagnostics = self.open_file_and_wait_for_diagnostics(solc, TEST_NAME)

        self.expect_equal(len(published_diagnostics), 1, "One published_diagnostics message")
        report = published_diagnostics[0]

        self.expect_equal(report['uri'], self.get_test_file_uri(TEST_NAME), "Correct file URI")
        diagnostics = report['diagnostics']

        self.expect_equal(len(diagnostics), 3, "3 diagnostic messages")
        self.expect_diagnostic(diagnostics[0], code=9574, lineNo= 7, startColumn= 8, endColumn=21)
        self.expect_diagnostic(diagnostics[1], code=6777, lineNo= 8, startColumn= 8, endColumn=15)
        self.expect_diagnostic(diagnostics[2], code=6160, lineNo=18, startColumn=15, endColumn=36)

    def test_textDocument_didOpen_with_relative_import(self, solc: JsonRpcProcess) -> None:
        self.setup_lsp(solc)
        TEST_NAME = 'didOpen_with_import'
        published_diagnostics = self.open_file_and_wait_for_diagnostics(solc, TEST_NAME, 2)

        self.expect_equal(len(published_diagnostics), 2, "Diagnostic reports for 2 files")

        # primary file:
        report = published_diagnostics[0]
        self.expect_equal(report['uri'], self.get_test_file_uri(TEST_NAME), "Correct file URI")
        self.expect_equal(len(report['diagnostics']), 0, "no diagnostics")

        # imported file (./lib.sol):
        report = published_diagnostics[1]
        self.expect_equal(report['uri'], self.get_test_file_uri('lib'), "Correct file URI")
        self.expect_equal(len(report['diagnostics']), 1, "one diagnostic")
        self.expect_diagnostic(report['diagnostics'][0], code=2072, lineNo=12, startColumn=8, endColumn=19)

    def test_textDocument_didOpen_with_relative_import_without_project_url(self, solc: JsonRpcProcess) -> None:
        self.setup_lsp(solc, expose_project_root=False)
        TEST_NAME = 'didOpen_with_import'
        published_diagnostics = self.open_file_and_wait_for_diagnostics(solc, TEST_NAME, 2)
        self.verify_didOpen_with_import_diagnostics(published_diagnostics)

    def verify_didOpen_with_import_diagnostics(self,
            published_diagnostics: List[Any],
            main_file_name='didOpen_with_import'):
        self.expect_equal(len(published_diagnostics), 2, "Diagnostic reports for 2 files")

        # primary file:
        report = published_diagnostics[0]
        self.expect_equal(report['uri'], self.get_test_file_uri(main_file_name), "Correct file URI")
        self.expect_equal(len(report['diagnostics']), 0, "one diagnostic")

        # imported file (./lib.sol):
        report = published_diagnostics[1]
        self.expect_equal(report['uri'], self.get_test_file_uri('lib'), "Correct file URI")
        self.expect_equal(len(report['diagnostics']), 1, "one diagnostic")
        self.expect_diagnostic(report['diagnostics'][0], code=2072, lineNo=12, startColumn=8, endColumn=19)

    def test_textDocument_didChange_updates_diagnostics(self, solc: JsonRpcProcess) -> None:
        self.setup_lsp(solc)
        TEST_NAME = 'publish_diagnostics_1'
        published_diagnostics = self.open_file_and_wait_for_diagnostics(solc, TEST_NAME)
        self.expect_equal(len(published_diagnostics), 1, "One published_diagnostics message")
        report = published_diagnostics[0]
        self.expect_equal(report['uri'], self.get_test_file_uri(TEST_NAME), "Correct file URI")
        diagnostics = report['diagnostics']
        self.expect_equal(len(diagnostics), 3, "3 diagnostic messages")
        self.expect_diagnostic(diagnostics[0], code=6321, lineNo=13, startColumn=44, endColumn=48)
        self.expect_diagnostic(diagnostics[1], code=2072, lineNo= 7, startColumn= 8, endColumn=19)
        self.expect_diagnostic(diagnostics[2], code=2072, lineNo=15, startColumn= 8, endColumn=20)

        solc.send_message(
            'textDocument/didChange',
            {
                'textDocument': {
                    'uri': self.get_test_file_uri(TEST_NAME)
                },
                'contentChanges': [
                    {
                        'range': {
                            'start': { 'line': 7, 'character': 1 },
                            'end': {   'line': 8, 'character': 1 }
                        },
                        'text': ""
                    }
                ]
            }
        )
        published_diagnostics = self.wait_for_diagnostics(solc, 1)
        self.expect_equal(len(published_diagnostics), 1)
        report = published_diagnostics[0]
        self.expect_equal(report['uri'], self.get_test_file_uri(TEST_NAME), "Correct file URI")
        diagnostics = report['diagnostics']
        text = report['_text']
        solc.trace("Document text", "\n" + text)
        self.expect_equal(len(diagnostics), 2)
        self.expect_diagnostic(diagnostics[0], code=6321, lineNo=12, startColumn=44, endColumn=48)
        self.expect_diagnostic(diagnostics[1], code=2072, lineNo=14, startColumn= 8, endColumn=20)

    def test_textDocument_didChange_delete_line(self, solc: JsonRpcProcess) -> None:
        # Reuse this test to prepare and ensure it is as expected
        self.test_textDocument_didOpen_with_relative_import(solc)
        # lib.sol: Fix the unused variable message by removing it.
        solc.send_message('textDocument/didChange', {
            'textDocument': {
                'uri': self.get_test_file_uri('lib')
            },
            'contentChanges': [
                {
                    'range': {
                        'start': { 'line': 12, 'character': 0 },
                        'end': { 'line': 12, 'character': 20 }
                    },
                    'text': ""
                }
            ]
        })
        published_diagnostics = self.wait_for_diagnostics(solc, 2)
        self.expect_equal(len(published_diagnostics), 2)
        report1 = published_diagnostics[0]
        self.expect_equal(report1['uri'], self.get_test_file_uri('didOpen_with_import'), "Correct file URI")
        self.expect_equal(len(report1['diagnostics']), 0, "no diagnostics")
        report2 = published_diagnostics[1]
        self.expect_equal(report2['uri'], self.get_test_file_uri('lib'), "Correct file URI")
        self.expect_equal(len(report2['diagnostics']), 0, "no diagnostics")

    def test_textDocument_didChange_at_eol(self, solc: JsonRpcProcess) -> None:
        """
        Append at one line and insert a new one below.
        """
        self.setup_lsp(solc)
        FILE_NAME = 'didChange_template'
        FILE_URI = self.get_test_file_uri(FILE_NAME)
        solc.send_message('textDocument/didOpen', {
            'textDocument': {
                'uri': FILE_URI,
                'languageId': 'Solidity',
                'version': 1,
                'text': self.get_test_file_contents(FILE_NAME)
            }
        })
        published_diagnostics = self.wait_for_diagnostics(solc, 1)
        solc.send_message('textDocument/didChange', {
            'textDocument': {
                'uri': FILE_URI
            },
            'contentChanges': [
                {
                    'range': {
                        'start': { 'line': 3, 'character': 7 },
                        'end': { 'line': 3, 'character': 7 }
                    },
                    'text': " C"
                }
            ]
        })
        published_diagnostics = self.wait_for_diagnostics(solc, 1)
        self.expect_equal(len(published_diagnostics), 1)
        report1 = published_diagnostics[0]
        self.expect_equal(report1['uri'], FILE_URI, "Correct file URI")
        self.expect_equal(len(report1['diagnostics']), 1, "one diagnostic")
        # TODO: not done yet. we're getting the wrong diagnostic back (as if we didn't edit)

    def test_textDocument_didChange_empty_file(self, solc: JsonRpcProcess) -> None:
        """
        Starts with an empty file and changes it to look like
        the didOpen_with_import test case. Then we can use
        the same verification calls to ensure it worked as expected.
        """
        # This FILE_NAME must be alphabetically before lib.sol to not over-complify
        # the test logic in verify_didOpen_with_import_diagnostics.
        FILE_NAME = 'a_new_file'
        FILE_URI = self.get_test_file_uri(FILE_NAME)
        self.setup_lsp(solc)
        solc.send_message('textDocument/didOpen', {
            'textDocument': {
                'uri': FILE_URI,
                'languageId': 'Solidity',
                'version': 1,
                'text': ''
            }
        })
        reports = self.wait_for_diagnostics(solc, 1)
        self.expect_equal(len(reports), 1)
        report = reports[0]
        published_diagnostics = report['diagnostics']
        self.expect_equal(len(published_diagnostics), 2)
        self.expect_diagnostic(published_diagnostics[0], code=1878, lineNo=0, startColumn=0, endColumn=0)
        self.expect_diagnostic(published_diagnostics[1], code=3420, lineNo=0, startColumn=0, endColumn=0)
        solc.send_message('textDocument/didChange', {
            'textDocument': {
                'uri': self.get_test_file_uri('a_new_file')
            },
            'contentChanges': [
                {
                    'range': {
                        'start': { 'line': 0, 'character': 0 },
                        'end': { 'line': 0, 'character': 0 }
                    },
                    'text': self.get_test_file_contents('didOpen_with_import')
                }
            ]
        })
        published_diagnostics = self.wait_for_diagnostics(solc, 2)
        self.verify_didOpen_with_import_diagnostics(published_diagnostics, 'a_new_file')

    # }}}
    # }}}

if __name__ == "__main__":
    suite = SolidityLSPTestSuite()
    exit_code = suite.main()
    exit(exit_code)
