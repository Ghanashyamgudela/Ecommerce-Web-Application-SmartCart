(function(){
    // Create cursor elements if they don't exist
    let cursor = document.getElementById('cursor');
    let cursorRing = document.getElementById('cursorRing');
    if (!cursor) {
        cursor = document.createElement('div');
        cursor.id = 'cursor';
        cursor.className = 'cursor';
        document.body.appendChild(cursor);
    }
    if (!cursorRing) {
        cursorRing = document.createElement('div');
        cursorRing.id = 'cursorRing';
        cursorRing.className = 'cursor-ring';
        document.body.appendChild(cursorRing);
    }

    let mx = 0, my = 0, rx = 0, ry = 0;

    document.addEventListener('mousemove', function(e) {
        mx = e.clientX; my = e.clientY;
        cursor.style.left = (mx - 6) + 'px';
        cursor.style.top  = (my - 6) + 'px';
    });

    function animateRing() {
        rx += (mx - rx - 18) * 0.12;
        ry += (my - ry - 18) * 0.12;
        cursorRing.style.left = rx + 'px';
        cursorRing.style.top  = ry + 'px';
        requestAnimationFrame(animateRing);
    }
    animateRing();

    // Scale cursor on interactive elements
    function bindHover() {
        document.querySelectorAll('a, button').forEach(function(el) {
            el.addEventListener('mouseenter', function() {
                cursor.style.transform = 'scale(2.5)';
                cursorRing.style.transform = 'scale(1.5)';
                cursorRing.style.borderColor = 'rgba(240,192,64,0.85)';
            });
            el.addEventListener('mouseleave', function() {
                cursor.style.transform = 'scale(1)';
                cursorRing.style.transform = 'scale(1)';
                cursorRing.style.borderColor = 'rgba(240,192,64,0.45)';
            });
        });
    }

    // Re-bind on DOM changes (simple mutation observer)
    bindHover();
    const mo = new MutationObserver(function(){ bindHover(); });
    mo.observe(document.body, { childList:true, subtree:true });
})();
