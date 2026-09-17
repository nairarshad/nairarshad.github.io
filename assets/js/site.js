'use strict';
// Text and links are rendered by Jekyll and work without JavaScript.
const menu = document.querySelector('.menu-toggle');
const navigation = document.getElementById('site-nav');
if (menu && navigation) {
  document.documentElement.classList.add('js');
  menu.addEventListener('click', () => {
    const open = menu.getAttribute('aria-expanded') !== 'true';
    menu.setAttribute('aria-expanded', String(open));
    navigation.classList.toggle('is-open', open);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu.getAttribute('aria-expanded') === 'true') {
      menu.setAttribute('aria-expanded', 'false');
      navigation.classList.remove('is-open');
      menu.focus();
    }
  });
}

