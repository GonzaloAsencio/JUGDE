import '@testing-library/jest-dom';
import { toHaveNoViolations } from 'jest-axe';

// axe-core matcher for the accessibility smoke suite (Capa 0 safety net).
expect.extend(toHaveNoViolations);

// jsdom doesn't implement scrollIntoView. Guarded: route-handler suites run
// under @jest-environment node, where Element doesn't exist.
if (typeof Element !== 'undefined') {
  Element.prototype.scrollIntoView = jest.fn();
}
