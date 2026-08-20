// Attrappe von cockpit.js, nur fuer die Vorschau am Arbeitsplatz.
// Kein Cockpit, kein Docker: sie beantwortet `docker ps` und `docker inspect`
// aus einem Zustand im Speicher, den Start/Stopp umlegen -- damit die echte
// index.html ohne Roboter bedienbar ist.
//
// Szenario ueber die Adresszeile waehlbar:
//   ?state=running | exited | created | paused | restarting | dead
//   ?state=missing        -> kein passender Container in der Liste
//   ?state=error          -> Docker antwortet nicht
//   &vnc=ok | nopw | bridge | beides   -> was die Diagnose finden soll
//   &name=<containername>              -> anderer compose-Projektname
//   &delay=2000                        -> Start/Stopp dauern so lange
(function () {
    const params = new URLSearchParams(window.location.search);
    let status = params.get('state') || 'exited';
    const vnc = params.get('vnc') || 'ok';
    const name = params.get('name') || 'offboard-lite-moveit-rviz-1';
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
        // Der grosse husky-offboard-Container steht immer mit in der Liste --
        // die Seite darf ihn nicht mitnehmen.
        const fremd = 'husky-offboard-offboard-1\tclearpath-offboard:jazzy\trunning\toffboard';
        if (status === 'missing')
            return fremd + '\n';
        return [
            name + '\thusky-offboard-lite:jazzy\t' + status + '\tmoveit-rviz',
            fremd,
        ].join('\n') + '\n';
    }

    function inspectOut() {
        const netz = (vnc === 'bridge' || vnc === 'beides') ? 'default' : 'host';
        const env = ['ROS_DOMAIN_ID=0', 'RVIZ_AUTOSTART=1'];
        if (vnc !== 'nopw' && vnc !== 'beides')
            env.push('VNC_PASSWORD=husky');
        return netz + '\n' + env.join('\n') + '\n';
    }

    window.cockpit = {
        transport: { host: 'localhost' },
        spawn(argv) {
            // argv = ['/bin/sh', '-c', <prefix>, 'sh', <docker-argumente...>]
            const args = argv.slice(4);
            const verb = args[0];

            if (status === 'error')
                return later(120, () => fail('Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?'));

            if (verb === 'ps')
                return later(120, () => psLines());

            if (verb === 'inspect')
                return later(120, () => inspectOut());

            if (verb === 'start')
                return later(delay, () => { status = 'running'; return '' });

            if (verb === 'stop')
                return later(delay, () => { status = 'exited'; return '' });

            return later(50, () => '');
        },
    };
}());
