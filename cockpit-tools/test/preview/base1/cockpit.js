// A dummy of cockpit.js, only for the preview at the workstation.
// No Cockpit, no Docker: it answers `docker ps` and `docker inspect` from a
// state in memory that start/stop flip over -- so that the real index.html can
// be operated without a robot.
//
// The scenario is selectable over the address bar:
//   ?state=running | exited | created | paused | restarting | dead
//   ?state=missing        -> no matching container in the list
//   ?state=error          -> Docker does not answer
//   &vnc=ok | nopw | bridge | both   -> what the diagnosis is meant to find
//   &desktop=up | down               -> is anybody listening on 5900 in there
//   &name=<container name>           -> a different compose project name
//   &delay=2000                      -> start/stop take that long
(function () {
    const params = new URLSearchParams(window.location.search);
    let status = params.get('state') || 'exited';
    const vnc = params.get('vnc') || 'ok';
    const name = params.get('name') || 'offboard-lite-moveit-rviz-1';
    const desktop = params.get('desktop') || 'up';
    const delay = parseInt(params.get('delay') || '1200', 10);

    function fail(message) {
        const ex = new Error(message);
        ex.exit_status = 1;
        return Promise.reject(ex);
    }

    function later(ms, fn) {
        return new Promise(resolve => window.setTimeout(() => resolve(fn()), ms));
    }

    function psLines() {
        // The big husky-offboard container always stands in the list too -- the
        // page must not take it along.
        const foreign = 'husky-offboard-offboard-1\tclearpath-offboard:jazzy\trunning\toffboard';
        if (status === 'missing')
            return foreign + '\n';
        return [
            name + '\thusky-offboard-lite:jazzy\t' + status + '\tmoveit-rviz',
            foreign,
        ].join('\n') + '\n';
    }

    function inspectOut() {
        const network = (vnc === 'bridge' || vnc === 'both') ? 'default' : 'host';
        const env = ['ROS_DOMAIN_ID=0', 'RVIZ_AUTOSTART=1'];
        if (vnc !== 'nopw' && vnc !== 'both')
            env.push('VNC_PASSWORD=husky');
        return network + '\n' + env.join('\n') + '\n';
    }

    window.cockpit = {
        transport: { host: 'localhost' },
        spawn(argv) {
            // argv = ['/bin/sh', '-c', <prefix>, 'sh', <docker arguments...>]
            const args = argv.slice(4);
            const verb = args[0];

            if (status === 'error')
                return later(120, () => fail('Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?'));

            if (verb === 'ps')
                return later(120, () => psLines());

            if (verb === 'inspect')
                return later(120, () => inspectOut());

            // docker exec <name> bash -c '<probe>'
            if (verb === 'exec')
                return later(80, () => desktop + '\n');

            if (verb === 'start')
                return later(delay, () => { status = 'running'; return '' });

            if (verb === 'stop')
                return later(delay, () => { status = 'exited'; return '' });

            return later(50, () => '');
        },
    };
}());
