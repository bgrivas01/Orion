// Monorepo setup: Metro has to watch the workspace root so it can follow the
// symlink into packages/shared, and resolve modules from the hoisted root
// node_modules as well as the app's own.
const { getDefaultConfig } = require("expo/metro-config");
const path = require("path");

const projectRoot = __dirname;
const workspaceRoot = path.resolve(projectRoot, "..");

const config = getDefaultConfig(projectRoot);

config.watchFolders = [workspaceRoot];
config.resolver.nodeModulesPaths = [
  path.resolve(projectRoot, "node_modules"),
  path.resolve(workspaceRoot, "node_modules"),
];
// Without this, Metro can resolve two copies of React in a workspace.
config.resolver.disableHierarchicalLookup = true;

module.exports = config;
