
contract C {
	function f(int a) public {}
	function f2(int a, string memory b) public {}
	function f3(int a, int b) public {}
	function f4() public {}

	function failFunctionArgsWrongType() public returns(bytes memory) {
		return abi.encodeCall(this.f, ("test"));
	}
	function failFunctionArgsTooMany() public returns(bytes memory) {
		return abi.encodeCall(this.f, (1, 2));
	}
	function failFunctionArgsTooFew0() public returns(bytes memory) {
		return abi.encodeCall(this.f, ());
	}
	function failFunctionArgsTooFew1() public returns(bytes memory) {
		return abi.encodeCall(this.f);
	}
	function failFunctionPtrMissing() public returns(bytes memory) {
		return abi.encodeCall(1, this.f);
	}
	function failFunctionPtrWrongType() public returns(bytes memory) {
		return abi.encodeCall(abi.encodeCall, (1, 2, 3, "test"));
	}
	function failFunctionArgsArrayLiteral() public returns(bytes memory) {
		return abi.encodeCall(this.f3, [1, 2]);
	}
	function successFunctionArgsIntLiteralTuple() public returns(bytes memory) {
		return abi.encodeCall(this.f, (1));
	}
	function successFunctionArgsIntLiteral() public returns(bytes memory) {
		return abi.encodeCall(this.f, 1);
	}
	function successFunctionArgsLiteralTuple() public returns(bytes memory) {
		return abi.encodeCall(this.f2, (1, "test"));
	}
	function successFunctionArgsEmptyTuple() public returns(bytes memory) {
		return abi.encodeCall(this.f4, ());
	}
}
// ----
// TypeError 5407: (254-262): Cannot implicitly convert component at position 0 from "literal_string "test"" to "int256".
// TypeError 7788: (344-374): Expected 1 instead of 2 components for the tuple parameter.
// TypeError 7788: (455-481): Expected 1 instead of 0 components for the tuple parameter.
// TypeError 6219: (562-584): Expected two arguments: a function pointer followed by a tuple.
// TypeError 5511: (679-680): Expected first argument to be a function pointer, not "int_const 1".
// TypeError 3509: (786-800): Function must be "public" or "external".
// TypeError 7515: (906-937): Expected a tuple with 2 components instead of a single non-tuple parameter.
// TypeError 5407: (930-936): Cannot implicitly convert component at position 0 from "uint8[2]" to "int256".
