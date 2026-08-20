// Attrappe von cockpit.js, nur fuer die Vorschau am Arbeitsplatz.
// Kein Cockpit, kein Docker: sie beantwortet `docker inspect` aus einem
// Zustand im Speicher, den Start/Stopp umlegen -- damit die echte index.html
// ohne Roboter bedienbar ist.
//
// Szenario ueber die Adresszeile waehlbar:
//   ?state=running | exited | created | paused | restarting | dead
//   ?state=missing        -> "No such object"
//   ?state=error          -> Docker antwortet nicht
//   &delay=2000           -> Start/Stopp brauchen so lange (gelbe Kugel ansehen)
(function () {
    const params = new URLSearchParams(window.location.search);
    let status = params.get('state') || 'exited';
    const delay = parseInt(params.get('delay') || '1200', 10);

    function fail(message) {
        const ex = new Error(message);
        ex.exit_status = 1;
        return Promise.reject(ex);
    }

    function later(ms, fn) {
        return new Promise(resolve => window.setTimeout(() => resolve(fn()), ms));
    }

    window.cockpit = {
        transport: { host: 'localhost' },
        spawn(argv) {
            // argv = ['/bin/sh', '-c', <prefix>, 'sh', <docker-argumente...>]
            const args = argv.slice(4);
            const verb = args[0];

            if (status === 'error')
                return later(120, () => fail('Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?'));

            if (status === 'missing') {
                if (verb === 'inspect')
                    return later(120, () => fail('Error: No such object: offboard-lite-moveit-rviz-1'));
                return later(120, () => fail('Error response from daemon: No such container: offboard-lite-moveit-rviz-1'));
            }

            if (verb === 'inspect')
                return later(120, () => status + '\n');

            if (verb === 'start')
                return later(delay, () => { status = 'running'; return '' });

            if (verb === 'stop')
                return later(delay, () => { status = 'exited'; return '' });

            return later(50, () => '');
        },
    };
}());
