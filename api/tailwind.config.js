/** @type {import('tailwindcss').Config} */
module.exports = {
  purge: ['./**/*.html'],
  darkMode: 'class',
  content: [
    'node_modules/preline/dist/*.js',
  ],
  theme: {
    extend: {
      colors: {
        'customblue': '#0064CF',
      },
    },
    screens: {
      'xs': '420px',
      'sm': '640px', 
      'md': '768px', 
      'lg': '1024px',
      'xl': '1280px',
    },
  },
}