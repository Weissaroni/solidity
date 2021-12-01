#!/usr/bin/env python3.8

import argparse
import json
import os
import subprocess

from typing import List, Union, Any
from deepdiff import DeepDiff

# {{{ JsonRpcProcess
class MyEncoder(json.JSONEncoder):
    """
    Encodes an object in JSON
    """
    def default(self, o): # pylint: disable=E0202
        return o.__dict__

class JsonRpcProcess:
    exe_path: str
    exe_args: List[str]
    process: subprocess.Popen
    trace_io: bool

    def __init__(self, exe_path: str, exe_args: List[str], trace_io: bool = False):
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

    def receive_message(self) -> Any:
        # `, timeout: float = 2.0`
        # Note, we should make use of timeout to avoid infinite blocking if nothing is received.
        LEN_HEADER = "Content-Length: "
        TYPE_HEADER = "Content-Type: "
        if self.process.stdout == None:
            return None
        message_size = None
        while True:
            #read header
            line = self.process.stdout.readline()
            if not line:
                # server quit
                return None
            line = line.decode("utf-8")
            if not line.endswith("\r\n"):
                raise RuntimeError("Bad header: missing newline")
            # remove the "\r\n"
            line = line[:-2]
            if line == "":
                break # done with the headers
            if line.startswith(LEN_HEADER):
                line = line[len(LEN_HEADER):]
                if not line.isdigit():
                    raise RuntimeError("Bad header: size is not int")
                message_size = int(line)
            elif line.startswith(TYPE_HEADER):
                # nothing todo with type for now.
                pass
            else:
                raise RuntimeError("Bad header: unknown header")
        if not message_size:
            raise RuntimeError("Bad header: missing size")
        rpc_message = self.process.stdout.read(message_size).decode("utf-8")
        self.trace('receive_message', rpc_message)
        return json.loads(rpc_message)

    def send_message(self, method_name: str, params: Any) -> None:
        if self.process.stdin == None:
            return
        message = { 'jsonrpc': '2.0', 'method': method_name, 'params': params }
        json_string = json.dumps(obj=message, cls=MyEncoder)
        rpc_message = f"Content-Length: {len(json_string)}\r\n\r\n{json_string}"
        self.trace(f'send_message ({method_name})', json_string)
        self.process.stdin.write(rpc_message.encode())
        self.process.stdin.flush()

    def call_method(self, method_name: str, params: Any) -> Any:
        self.send_message(method_name, params)
        return self.receive_message()

    def send_notification(self, name: str, params: Any = None) -> None:
        self.send_message(name, params)

# }}}

SGR_RESET = '\033[m'
SGR_TRACE = '\033[1;36m'
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
            f"Expectation failed. Expected {expected} but got {actual}. {diff}"
        )

# pylint: disable-next=too-many-instance-attributes
class SolidityLSPTestSuite: # {{{
    tests_passed: int = 0
    tests_failed: int = 0
    assertion_count: int = 0   # number of total assertions executed so far
    assertions_passed: int = 0
    assertions_failed: int = 0
    print_assertions: bool = False

    def __init__(self):
        self.solc_path, self.project_root_dir, self.print_assertions = self.parse_args_and_prepare()
        self.project_root_uri = 'file://' + self.project_root_dir

    def parse_args_and_prepare(self):
        """
        Parses CLI args and returns tuple of path to solc executable
        and path to solidity-project root dir.
        """
        parser = argparse.ArgumentParser(description='Solidity LSP Test suite')
        parser.set_defaults(print_assertions=False)
        parser.add_argument(
            '-v, --print-assertions',
            dest='print_assertions',
            action='store_true',
            help='Be more verbose by also printing assertions.'
        )
        parser.add_argument(
            'solc_path',
            type=str,
            default="/home/trapni/work/solidity/build/solc/solc",
            help='Path to solc binary to test against',
            nargs="?"
        )
        parser.add_argument(
            'project_root_dir',
            type=str,
            default=f"{os.path.dirname(os.path.realpath(__file__))}/..",
            help='Path to Solidity project\'s root directory (must be fully qualified).',
            nargs="?"
        )
        args = parser.parse_args()
        project_root_dir = os.path.realpath(args.project_root_dir) + '/test/libsolidity/lsp'
        return [args.solc_path, project_root_dir, args.print_assertions]

    def main(self) -> int:
        """
        Runs all test cases.
        Returns 0 on success and the number of failing assertions (capped to 127) otherwise.
        """

        for method_name in sorted([name for name
                            in dir(SolidityLSPTestSuite)
                            if callable(getattr(SolidityLSPTestSuite, name)) and
                                name.startswith("test_")]):
            test_fn = getattr(self, method_name)
            title: str = test_fn.__name__
            if test_fn.__doc__ != None:
                title = test_fn.__doc__.strip()
            print(f"{SGR_TEST_BEGIN}Testing {title} ...{SGR_RESET}")
            try:
                with JsonRpcProcess(self.solc_path, ["--lsp"]) as solc:
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
        project_root_uri = 'file://' + self.project_root_dir
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
        return open(self.get_test_file_path(test_case_name), mode="r", encoding="utf-8").read()

    def extract_params_for_method(self, method_name: str, message: Any) -> Union[Any, None]:
        if message['method'] != method_name:
            return None
        return message['params']

    def open_file_and_wait_for_diagnostics(self,
                                           solc: JsonRpcProcess,
                                           test_case_name: str,
                                           diagnostic_reports: int = 1) -> List[Any]:
        """
        Opens file for given test case and waits for diagnostics to be published.
        """
        reports = []
        reply = solc.call_method('textDocument/didOpen',
            {
                'textDocument': {
                    'uri': self.get_test_file_uri(test_case_name),
                    'languageId': 'Solidity',
                    'version': 1,
                    'text': self.get_test_file_contents(test_case_name)
                }
            }
        )
        diags = self.extract_params_for_method('textDocument/publishDiagnostics', reply)
        if diags == None:
            raise RuntimeError(f"Unepxected response from RPC endpoint: {reply}")
        reports.append(diags)
        # reply now contains one "textDocument/publishDiagnostics" notification
        while diagnostic_reports > 1:
            diagnostic_reports -= 1
            reply = solc.receive_message()
            diags = self.extract_params_for_method('textDocument/publishDiagnostics', reply)
            if diags == None:
                raise RuntimeError(f"Unepxected response from RPC endpoint: {reply}")
            reports.append(diags)
        return reports

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

    # pylint: disable-next=too-many-arguments
    def expect_diagnostic(self, diagnostic, code: int, lineNo: int, startColumn: int, endColumn: int):
        self.expect_equal(diagnostic['code'], code, f'diagnostic: {code}')
        self.expect_equal(
            diagnostic['range'],
            {'end': {'character': endColumn, 'line': lineNo},
             'start': {'character': startColumn, 'line': lineNo}},
            "diagnostic: check range"
        )
    # }}}

    # {{{ actual tests
    def test_publish_diagnostics_1(self, solc: JsonRpcProcess) -> None:
        """ Publish diagnostics (warnings) """
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

    def test_publish_diagnostics_2(self, solc: JsonRpcProcess) -> None:
        """ Publish diagnostics (errors) """
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

    def test_didOpen_with_relative_import(self, solc: JsonRpcProcess) -> None:
        """ didOpen with relative import """
        self.setup_lsp(solc)
        TEST_NAME = 'didOpen_with_import'
        published_diagnostics = self.open_file_and_wait_for_diagnostics(solc, TEST_NAME, 2)

        self.expect_equal(len(published_diagnostics), 2, "Diagnostic reports for 2 files")

        # primary file:
        report = published_diagnostics[0]
        self.expect_equal(report['uri'], self.get_test_file_uri(TEST_NAME), "Correct file URI")
        self.expect_equal(len(report['diagnostics']), 0, "one diagnostic")

        # imported file (./lib.sol):
        report = published_diagnostics[1]
        self.expect_equal(report['uri'], self.get_test_file_uri('lib'), "Correct file URI")
        self.expect_equal(len(report['diagnostics']), 1, "one diagnostic")
        self.expect_diagnostic(report['diagnostics'][0], code=2072, lineNo=12, startColumn=8, endColumn=19)

    def test_didOpen_with_relative_import_without_project(self, solc: JsonRpcProcess) -> None:
        """ didOpen with relative import with no project URL given """
        self.setup_lsp(solc, expose_project_root=False)
        TEST_NAME = 'didOpen_with_import'
        published_diagnostics = self.open_file_and_wait_for_diagnostics(solc, TEST_NAME, 2)

        self.expect_equal(len(published_diagnostics), 2, "Diagnostic reports for 2 files")

        # primary file:
        report = published_diagnostics[0]
        self.expect_equal(report['uri'], self.get_test_file_uri(TEST_NAME), "Correct file URI")
        self.expect_equal(len(report['diagnostics']), 0, "one diagnostic")

        # imported file (./lib.sol):
        report = published_diagnostics[1]
        self.expect_equal(report['uri'], self.get_test_file_uri('lib'), "Correct file URI")
        self.expect_equal(len(report['diagnostics']), 1, "one diagnostic")
        self.expect_diagnostic(report['diagnostics'][0], code=2072, lineNo=12, startColumn=8, endColumn=19)
    # }}}
    # }}}

if __name__ == "__main__":
    suite = SolidityLSPTestSuite()
    rv = suite.main()
    exit(rv)
