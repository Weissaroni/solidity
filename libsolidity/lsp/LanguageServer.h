/*
	This file is part of solidity.

	solidity is free software: you can redistribute it and/or modify
	it under the terms of the GNU General Public License as published by
	the Free Software Foundation, either version 3 of the License, or
	(at your option) any later version.

	solidity is distributed in the hope that it will be useful,
	but WITHOUT ANY WARRANTY; without even the implied warranty of
	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
	GNU General Public License for more details.

	You should have received a copy of the GNU General Public License
	along with solidity.  If not, see <http://www.gnu.org/licenses/>.
*/
// SPDX-License-Identifier: GPL-3.0
#pragma once

#include <libsolidity/interface/CompilerStack.h>
#include <libsolidity/interface/FileReader.h>
#include <libsolidity/lsp/Transport.h>

#include <json/value.h>

#include <functional>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace solidity::lsp
{

enum class ErrorCode;

/// Solidity Language Server, managing one LSP client.
///
/// This implements a subset of LSP version 3.16 that can be found at:
///     https://microsoft.github.io/language-server-protocol/specifications/specification-3-16/
class LanguageServer
{
public:
	/// @param _transport Customizable transport layer.
	explicit LanguageServer(Transport& _transport);

	/// Re-compiles the project and updates the diagnostics pushed to the client.
	void compileAndUpdateDiagnostics();

	/// Loops over incoming messages via the transport layer until shutdown condition is met.
	///
	/// The standard shutdown condition is when the maximum number of consecutive failures
	/// has been exceeded.
	///
	/// @return boolean indicating normal or abnormal termination.
	bool run();

protected:
	void handleInitialize(MessageID _id, Json::Value const& _args);
	void handleWorkspaceDidChangeConfiguration(MessageID _id, Json::Value const& _args);
	void handleTextDocumentDidOpen(MessageID _id, Json::Value const& _args);
	void handleTextDocumentDidChange(MessageID _id, Json::Value const& _args);

	/// Invoked when the server user-supplied configuration changes (initiated by the client).
	void changeConfiguration(Json::Value const&);

	/// Compile everything until after analysis phase.
	void compile();

	std::optional<langutil::SourceLocation> parsePosition(
		std::string const& _sourceUnitName,
		Json::Value const& _position
	) const;
	/// @returns the source location given a source unit name and an LSP Range object,
	/// or nullopt on failure.
	std::optional<langutil::SourceLocation> parseRange(
		std::string const& _sourceUnitName,
		Json::Value const& _range
	) const;
	Json::Value toRange(langutil::SourceLocation const& _location) const;
	Json::Value toJson(langutil::SourceLocation const& _location) const;

	/// Translates an LSP client path to the internal source unit name for the compiler.
	std::string clientPathToSourceUnitName(std::string const& _path) const;
	/// Translates a compiler-internal source unit name to an LSP client path.
	std::string sourceUnitNameToClientPath(std::string const& _sourceUnitName) const;
	/// @returns true if we store the source for given the LSP client path.
	bool clientPathSourceKnown(std::string const& _path) const;

	// LSP related member fields
	using Handler = std::function<void(MessageID, Json::Value const&)>;

	Transport& m_client;
	std::map<std::string, Handler> m_handlers;
	/// Server shutdown (but not process exit) has been requested by the client.
	bool m_shutdownRequested = false;
	/// Server process exit has been requested by the client.
	bool m_exitRequested = false;

	/// FileReader is used for reading files during comilation phase but is also used as VFS for the LSP.
	frontend::FileReader m_fileReader;

	frontend::CompilerStack m_compilerStack;

	/// User-supplied custom configuration settings (such as EVM version).
	Json::Value m_settingsObject;
};

}
