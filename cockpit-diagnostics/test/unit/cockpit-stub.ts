// Stand-in for the `cockpit` module outside the browser. Only the calls the
// tested code paths use; translation is identity, so tests assert English.
const cockpit = {
    gettext: (s: string) => s,
    ngettext: (singular: string, plural: string, n: number) => (n === 1 ? singular : plural),
    format: (fmt: string, ...args: unknown[]) =>
        fmt.replace(/\$(\d)/g, (_m, i) => String(args[Number(i)])),
};
export default cockpit;
