// Stand-in for the `cockpit` module outside the browser. Only the two calls the
// tested code paths use; translation is identity, so tests assert English.
const cockpit = {
    gettext: (s: string) => s,
    format: (fmt: string, ...args: unknown[]) =>
        fmt.replace(/\$(\d)/g, (_m, i) => String(args[Number(i)])),
};
export default cockpit;
