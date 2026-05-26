/* ═══════════════════════════════════════
   ILIBOM-IN · main.js
═══════════════════════════════════════ */

// ── MODALES ──
function openModal(id) {
    document.getElementById(id).classList.add('open');
}
function closeModal(id) {
    document.getElementById(id).classList.remove('open');
}

// Cerrar modal al hacer clic fuera
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.modal-overlay').forEach(function (m) {
        m.addEventListener('click', function (e) {
            if (e.target === this) this.classList.remove('open');
        });
    });

    // ── CALENDARIO ──
    buildCalendar();

    // ── AUTO-DISMISS FLASH ──
    setTimeout(function () {
        document.querySelectorAll('.alert').forEach(function (a) {
            a.style.transition = 'opacity .5s';
            a.style.opacity = '0';
            setTimeout(() => a.remove(), 500);
        });
    }, 4000);
});

// ── CALENDARIO (Agenda) ──
function buildCalendar() {
    var grid = document.getElementById('cal-grid');
    if (!grid) return;

    var events = {
        10: 'Carlos M.',
        14: 'Laura R.',
        16: 'Roberto J.',
        22: 'Fam. Guerrero',
        26: '3 citas hoy',
        28: 'María T.'
    };

    for (var i = 1; i <= 31; i++) {
        var d = document.createElement('div');
        d.className = 'cal-day';

        var num = document.createElement('div');
        num.className = 'cal-day-num';
        num.textContent = i;

        if (i === 26) {
            num.style.color = '#059669';
            num.style.fontWeight = '700';
            d.style.borderColor = '#059669';
        }
        d.appendChild(num);

        if (events[i]) {
            var ev = document.createElement('div');
            ev.className = 'cal-event';
            ev.textContent = events[i];
            (function (day) {
                ev.onclick = function () { showAlert('Cita del día ' + day, 'success'); };
            })(i);
            d.appendChild(ev);
        }
        grid.appendChild(d);
    }
}

// ── ALERTA EN PANTALLA (sin flash de Flask) ──
function showAlert(msg, type) {
    var div = document.createElement('div');
    div.className = 'alert alert-' + (type || 'success');
    div.textContent = msg;

    var main = document.querySelector('.main-content');
    main.insertBefore(div, main.firstChild);

    setTimeout(function () {
        div.style.transition = 'opacity .5s';
        div.style.opacity = '0';
        setTimeout(() => div.remove(), 500);
    }, 3500);
}

// ── CONFIRMAR BAJA (RF-06 / RF-18) ──
function confirmarBaja(tipo, nombre) {
    var msg = tipo === 'usuario'
        ? '¿Dar de baja a ' + nombre + '? (RF-18: borrado lógico — sus registros se conservan)'
        : '¿Eliminar propiedad ' + nombre + '? (RF-06)';
    return confirm(msg);
}

// ── VALIDAR TELÉFONO (RF-14) ──
function validarTelefono(input) {
    var val = input.value.replace(/\D/g, '');
    input.value = val;
    if (val.length !== 10 && val.length > 0) {
        input.style.borderColor = '#ef4444';
        input.title = 'RF-14: El teléfono debe tener exactamente 10 dígitos';
    } else {
        input.style.borderColor = val.length === 10 ? '#059669' : '';
        input.title = '';
    }
}

// ── ENVIAR WHATSAPP (RF-14) ──
function enviarWhatsApp(telefono, nombre) {
    if (!telefono || telefono.replace(/\D/g, '').length !== 10) {
        showAlert('RF-14: El teléfono de ' + nombre + ' no tiene el formato de 10 dígitos requerido', 'error');
        return;
    }
    var num = '52' + telefono.replace(/\D/g, '');
    var msg = encodeURIComponent('Hola ' + nombre + ', le comparto información de una propiedad que puede ser de su interés.');
    window.open('https://wa.me/' + num + '?text=' + msg, '_blank');
}

// ── FILTROS DE TABLA ──
function filtrarTabla(inputId, tablaId) {
    var val = document.getElementById(inputId).value.toLowerCase();
    var rows = document.querySelectorAll('#' + tablaId + ' tbody tr');
    rows.forEach(function (r) {
        r.style.display = r.textContent.toLowerCase().includes(val) ? '' : 'none';
    });
}