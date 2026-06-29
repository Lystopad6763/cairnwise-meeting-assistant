import { Link, isRouteErrorResponse, useRouteError } from 'react-router-dom';
import { AlertTriangle, Home } from 'lucide-react';
import { ApiError } from '../lib/api';
import { Button } from './ui/Button';
import { Card } from './ui/Card';

/**
 * Friendly UA error card for the shell's errorElement.
 * Treats ApiError.status === 404 (and router 404s) as "not found".
 */
export function RouteErrorBoundary() {
  const error = useRouteError();

  let title = 'Щось пішло не так';
  let description = 'Сталася неочікувана помилка. Спробуйте оновити сторінку.';

  if (error instanceof ApiError) {
    if (error.status === 404) {
      title = 'Не знайдено';
      description = 'Запитаний ресурс не існує або був видалений.';
    } else if (error.status === 0) {
      title = 'Бекенд недоступний';
      description = 'Не вдалося зв’язатися з сервером. Перевірте, що API запущено.';
    } else {
      description = error.detail || description;
    }
  } else if (isRouteErrorResponse(error)) {
    if (error.status === 404) {
      title = 'Сторінку не знайдено';
      description = 'Такої сторінки не існує.';
    } else {
      title = `Помилка ${error.status}`;
      description = error.statusText || description;
    }
  } else if (error instanceof Error) {
    description = error.message || description;
  }

  return (
    <div className="mx-auto max-w-md py-16">
      <Card className="flex flex-col items-center gap-4 px-6 py-10 text-center">
        <span className="flex h-12 w-12 items-center justify-center rounded-full bg-status-failed/15 text-status-failed">
          <AlertTriangle className="h-6 w-6" aria-hidden="true" />
        </span>
        <h1 className="text-lg font-semibold text-fg">{title}</h1>
        <p className="text-sm text-muted">{description}</p>
        <Link to="/">
          <Button variant="secondary" icon={Home}>
            На головну
          </Button>
        </Link>
      </Card>
    </div>
  );
}

export default RouteErrorBoundary;
