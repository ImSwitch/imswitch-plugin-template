// ─────────────────────────────────────────────────────────────────────────────
//  Webpack config for the plugin frontend.
//
//  Produces dist/remoteEntry.js — the one file the ImSwitch shell fetches at
//  runtime from /imswitch/plugin/<name>/ui/remoteEntry.js. The host does not
//  bundle any of this code.
//
//  THE DEPENDENCY CONTRACT — read this before changing the `shared` block:
//
//   1. eager: false. The HOST is the eager provider of every shared package.
//      A remote with eager:true forces its own copy of React into its bundle,
//      and you get "invalid hook call" at mount time with nothing in the error
//      pointing at Module Federation as the cause. This is the single most
//      expensive mistake you can make here.
//
//   2. fallback: false (webpack `import: false`). By default webpack ALSO emits
//      a local copy of each shared package as a fallback for when the host does
//      not provide it. For a plugin that fallback is just the duplicate-React
//      bug deferred to runtime, so it is switched off. The plugin now fails
//      loudly at load if the host is missing something, and the shell shows
//      that error.
//
//   3. The list itself comes from ./shared-deps.js, which is a VERBATIM copy of
//      ImSwitch's frontend/shared-deps.js. CI diffs the two so they cannot
//      silently drift. Do not hand-edit the shared block here.
// ─────────────────────────────────────────────────────────────────────────────
const path = require("path");
const { ModuleFederationPlugin } = require("webpack").container;

const { makeShared } = require("./shared-deps");

// MUST match [plugin.ui].scope and [plugin.ui].exposed in plugin.toml.
// `make check` fails the build if these drift apart.
const SCOPE = "example_plugin";
const EXPOSED = "./Widget";

module.exports = (_, argv) => ({
  entry: "./src/index.js",
  mode: argv.mode || "development",
  output: {
    path: path.resolve(__dirname, "dist"),
    filename: "[name].js",
    // 'auto' resolves chunk URLs relative to the document remoteEntry.js was
    // loaded from, so chunks resolve correctly under the plugin's mount point
    // without hard-coding it.
    publicPath: "auto",
    clean: true,
  },
  devServer: { port: 3102, historyApiFallback: true },
  module: {
    rules: [
      {
        test: /\.(js|jsx)$/,
        loader: "babel-loader",
        exclude: /node_modules/,
        options: { presets: ["@babel/preset-env", "@babel/preset-react"] },
      },
    ],
  },
  plugins: [
    new ModuleFederationPlugin({
      name: SCOPE,
      filename: "remoteEntry.js",
      exposes: { [EXPOSED]: "./src/Widget.jsx" },

      // Import the host's own modules:
      //   import store from "host_app/store";
      //   import { useWebSocket } from "host_app/contexts";
      remotes: {
        host_app: "host_app@/imswitch/ui/remoteEntry.js",
      },

      shared: makeShared({ eager: false, fallback: false }),
    }),
  ],
  resolve: { extensions: [".js", ".jsx"] },
});
