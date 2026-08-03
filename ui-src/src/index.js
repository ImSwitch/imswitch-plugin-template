// Async boundary.
//
// The entry point must not import the widget synchronously: Module Federation
// needs a tick to negotiate the share scope with the host before any shared
// module (React, MUI, react-redux) is touched. A static import here would
// evaluate the widget — and therefore React — too early, which is what produces
// "Shared module is not available for eager consumption".
//
// This one-line file is the standard fix. Leave it alone.
import("./Widget");
